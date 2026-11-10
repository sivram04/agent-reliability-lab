"""`arl` command line."""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

import typer

from . import labels as labels_mod
from . import suites
from .adapters import build_agent
from .cassette import Cassette
from .llm import PROVIDERS, build_llm
from .models import RunResult, Target
from .runner import RunConfig, run_suite, summarize
from .stats import compare as compare_runs
from .store import Store
from .tracing import setup_otel, shutdown_otel
from .usage import load_prices

app = typer.Typer(help="Agent Reliability Lab: chaos engineering for AI agents.")


def _version(value: bool) -> None:
    if value:
        from . import __version__

        typer.echo(f"arl {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(False, "--version", callback=_version, is_eager=True, help="Show version and exit."),
    plugin: list[str] = typer.Option([], "--plugin", help="Import a plugin module (repeatable). Also: ARL_PLUGINS."),
) -> None:
    """Agent Reliability Lab: chaos engineering for AI agents."""
    for stream in (sys.stdout, sys.stderr):
        try:  # redirected output on Windows defaults to a legacy code page: never crash on a character
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.path.insert(0, str(Path.cwd()))
    from . import plugins

    try:
        plugins.load(plugin)
    except ImportError as exc:
        raise typer.BadParameter(f"cannot import plugin: {exc}", param_hint="--plugin") from exc
label_app = typer.Typer(help="Human labels and judge-human agreement.")
app.add_typer(label_app, name="label")

LLM_HELP = f"'openai' (ARL_LLM_* env vars), PROVIDER:MODEL ({', '.join(PROVIDERS)}) or 'python:module:fn'."


def _load_target(path: Path) -> Target:
    from .models import ConfigError

    try:
        return Target.load(path)
    except ConfigError as exc:
        raise typer.BadParameter(str(exc), param_hint="--target") from exc


def _build(tgt: Target, path: Path):
    """Build the agent, turning import and wiring problems into a message about the target file."""
    try:
        return build_agent(tgt)
    except (ValueError, ImportError, AttributeError, TypeError) as exc:
        raise typer.BadParameter(f"{path}: can't load the agent: {exc}", param_hint="--target") from exc


def _check_dbs(dbs: list[Path]) -> None:
    import sqlite3

    for db in dbs:
        try:
            con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
            try:
                con.execute("SELECT id, target, summary FROM runs LIMIT 1").fetchall()
            finally:
                con.close()
        except sqlite3.DatabaseError as exc:
            raise typer.BadParameter(f"{db}: not an Agent Reliability Lab results database ({exc})",
                                     param_hint="--db") from exc


def _usage_line(role: str, row: dict) -> str:
    cost = "cost n/a" if row["cost_usd"] is None else f"${row['cost_usd']:.4f}"
    return f"{role}: {row['input_tokens']}+{row['output_tokens']} ({cost})"


def _pct(x) -> str:
    return "n/a" if x is None else f"{x:.0%}"


@app.command()
def run(
    target: Path = typer.Option(..., help="Target YAML file."),
    suite: str | None = typer.Option(None, help="Scenario paths and/or built-in packs, comma-separated "
                                     "(builtin:smoke, builtin:safety, builtin:library). Omit for an empty suite."),
    repeats: int = typer.Option(1, min=1),
    seed: int = 0,
    concurrency: int = typer.Option(4, min=1),
    db: Path = typer.Option(Path("arl.db"), help="SQLite results file."),
    min_pass_rate: float = typer.Option(0.0, help="Exit 1 if the pass rate falls below this."),
    json_out: Path | None = typer.Option(None, help="Write the summary JSON here."),
    results_out: Path | None = typer.Option(None, help="Write full results JSON here (a baseline for compare)."),
    cassette: Path | None = typer.Option(None, help="Cassette file for record/replay."),
    record_mode: str = typer.Option("off", help="off | record | replay (needs --cassette)."),
    junit_out: Path | None = typer.Option(None, help="Write JUnit XML (one testcase per scenario run)."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="List every failing run."),
    otel: str | None = typer.Option(None, help="Export traces: console | otlp."),
    user_llm: str | None = typer.Option(None, help=f"Simulated-user LLM: {LLM_HELP}"),
    judge_llm: str | None = typer.Option(None, help=f"Judge LLM: {LLM_HELP}"),
):
    """Run a scenario suite against a target agent."""
    sys.path.insert(0, str(Path.cwd()))
    if record_mode != "off" and not cassette:
        raise typer.BadParameter("--record-mode needs --cassette")
    if record_mode not in ("off", "record", "replay"):
        raise typer.BadParameter("must be off, record or replay", param_hint="--record-mode")
    if not 0.0 <= min_pass_rate <= 1.0:
        raise typer.BadParameter("must be between 0 and 1, e.g. 0.95", param_hint="--min-pass-rate")
    for out in (json_out, results_out, junit_out):
        if out is not None:
            out.parent.mkdir(parents=True, exist_ok=True)
    try:
        setup_otel(otel)
    except ImportError as exc:
        raise typer.BadParameter(f"needs the otel extra: pip install 'agent-reliability-lab[otel]' ({exc})",
                                 param_hint="--otel") from exc
    tgt = _load_target(target)
    load_prices(tgt.prices)
    try:
        scenarios, skipped = suites.bind(suites.load(suite), tgt, judge=bool(judge_llm) or record_mode == "replay")
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--suite") from exc
    if skipped:
        reasons = sorted({why for _, why in skipped})
        typer.echo(f"skipped {len(skipped)} scenario(s): {'; '.join(reasons)}")
    tape = Cassette(cassette, record_mode) if cassette else None
    replay = record_mode == "replay"
    # Replay never builds the real agent or LLMs, so it works offline.
    agent = None if replay else _build(tgt, target)
    try:
        user = None if replay else build_llm(user_llm, role="user")
        judge = None if replay else build_llm(judge_llm, temperature=0.0, role="judge")  # repeatable verdicts
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--user-llm/--judge-llm") from exc
    if not scenarios:
        typer.echo("warning: no scenarios to run (pass --suite, e.g. builtin:quick)")
    if tape:
        agent = tape.wrap(agent)
        user = tape.wrap(user, "user") if user_llm else None
        judge = tape.wrap(judge, "judge") if judge_llm else None
    cfg = RunConfig(repeats=repeats, seed=seed, concurrency=concurrency, user_llm=user, judge_llm=judge,
                    secrets=tgt.secrets)
    results = asyncio.run(run_suite(agent, scenarios, cfg=cfg))
    if tape:
        tape.save()
    shutdown_otel()
    summary = summarize(results)
    with Store(db) as store:
        run_id = store.save_run(tgt, results, summary, str(suite or ""))
    # Write machine-readable outputs before printing anything, so CI always gets them.
    if json_out:
        json_out.write_text(json.dumps({"run_id": run_id, "target": tgt.name, "version": tgt.version, **summary},
                                       indent=2), encoding="utf-8")
    if results_out:
        from .redact import redact_results

        _write_results(results_out, redact_results(results, tgt.secrets))
    if junit_out:
        from .junit import write as write_junit

        write_junit(junit_out, results, tgt.name, tgt.secrets)

    typer.echo(f"run {run_id}  target={tgt.name}@{tgt.version}  scenarios={len(scenarios)}  repeats={repeats}")
    if verbose:
        for r in results:
            if not r.passed:
                failed = [c.name for c in r.checks if not c.passed]
                typer.echo(f"  FAIL {r.scenario_id}#{r.repeat}: {r.error or ', '.join(failed)}")
    lo, hi = summary["pass_rate_ci95"]
    typer.echo(f"pass rate {summary['pass_rate']:.0%} ({summary['passed']}/{summary['runs']}), 95% CI {lo:.0%}-{hi:.0%}")
    sc = summary["scenarios"]
    if repeats > 1:
        typer.echo(f"scenarios: {sc['always_pass']} always pass, {len(sc['always_fail'])} always fail, "
                   f"{len(sc['flaky'])} flaky (out of {sc['total']})")
    for cat, rate in summary["by_category"].items():
        typer.echo(f"  {cat:<20} {rate:.0%}")
    typer.echo(
        f"recovery {_pct(summary['recovery_rate'])}  safety violations {_pct(summary['safety_violation_rate'])}  "
        f"loops {_pct(summary['loop_rate'])}  hallucinations {_pct(summary['hallucination_rate'])}  "
        f"p95 {summary['p95_latency_s']:.2f}s"
    )
    if summary["usage"]:
        typer.echo("tokens " + "  ".join(_usage_line(role, row) for role, row in summary["usage"].items()))
    from .explain import explain, headline
    from .explain import render as render_findings

    findings = explain(results, tgt.secrets)
    typer.echo(f"\n{headline(findings, len(scenarios))}")
    if findings:
        typer.echo(render_findings(findings) + ("" if verbose else "\n(--verbose lists every failing run)"))
    if not results and min_pass_rate > 0:
        typer.echo("gate: no scenarios ran, so --min-pass-rate cannot be met")
        raise typer.Exit(1)
    if summary["pass_rate"] < min_pass_rate:
        raise typer.Exit(1)


def _write_results(path: Path, results: list[RunResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([r.model_dump() for r in results], default=str), encoding="utf-8")


def _load_results(spec: str, db: Path) -> list[RunResult]:
    """A run id in the database, or a results JSON file from --results-out."""
    path = Path(spec)
    if path.suffix == ".json":
        if not path.is_file():
            raise typer.BadParameter(f"{spec}: results file not found")
        results = [RunResult.model_validate(r) for r in json.loads(path.read_text(encoding="utf-8"))]
    else:
        _require_db(db)
        with Store(db) as store:
            results = store.load_results(spec)
    if not results:
        # An unknown id must never look like "no regression" to a CI gate.
        raise typer.BadParameter(f"{spec}: no results (unknown run id in {db}, or an empty results file)")
    return results


def _require_db(db: Path) -> None:
    """Read-only commands must not create an empty database at a mistyped path."""
    if not db.is_file():
        raise typer.BadParameter(f"{db}: no results database here; run `arl run` first or pass --db",
                                 param_hint="--db")
    _check_dbs([db])


@app.command()
def runs(db: Path = typer.Option(Path("arl.db"))):
    """List past runs."""
    _require_db(db)
    with Store(db) as store:
        rows = store.list_runs()
    for run_id, name, version, created, summary in rows:
        s = json.loads(summary)
        typer.echo(f"{run_id}  {created[:19]}  {name}@{version}  {s['pass_rate']:.0%} of {s['runs']}")


@app.command()
def compare(
    base: str = typer.Argument(..., help="Baseline run id or results JSON."),
    new: str = typer.Argument(..., help="Candidate run id or results JSON."),
    db: Path = typer.Option(Path("arl.db")),
    alpha: float = typer.Option(0.05, help="Significance level."),
    max_drop: float = typer.Option(0.0, help="Ignore drops smaller than this (absolute pass rate)."),
    json_out: Path | None = typer.Option(None),
):
    """Compare two runs. Exits 1 on a statistically significant regression."""
    report = compare_runs(_load_results(base, db), _load_results(new, db), alpha, max_drop)
    typer.echo(f"{'metric':<34} {'base':>7} {'new':>7} {'delta':>7} {'p':>7}")
    for row in report["rows"]:
        fmt = (lambda v: f"{v:.2f}") if row["metric"].startswith("latency") else (lambda v: f"{v:.0%}")
        flag = "  REGRESSION" if row["regression"] else ""
        typer.echo(f"{row['metric']:<34} {fmt(row['base']):>7} {fmt(row['new']):>7} "
                   f"{row['delta']:>+7.2f} {row['p_value']:>7.3f}{flag}")
    typer.echo("RESULT: regression" if report["regression"] else "RESULT: no significant regression")
    if json_out:
        json_out.write_text(json.dumps(report, indent=2))
    if report["regression"]:
        raise typer.Exit(1)


@app.command()
def report(
    run_id: str = typer.Argument(..., help="Run id (or 'latest')."),
    out: Path = typer.Option(..., help="HTML file to write; a .json summary is written next to it."),
    baseline: str | None = typer.Option(None, help="Baseline run id or results JSON, for a comparison section."),
    db: Path = typer.Option(Path("arl.db")),
):
    """HTML report card with failing traces you can replay step by step."""
    from .report import render_report, write

    _require_db(db)
    with Store(db) as store:
        listed = store.list_runs()
        if not listed:
            raise typer.BadParameter(f"{db}: no runs yet", param_hint="--db")
        if run_id == "latest":
            run_id = listed[0][0]
        try:
            run = store.get_run(run_id)
        except KeyError as exc:
            raise typer.BadParameter(f"no run {run_id!r} in {db}; see `arl runs`", param_hint="RUN_ID") from exc
        results = store.load_results(run_id)
    write(out, render_report(run, results, _load_results(baseline, db) if baseline else None))
    write(out.with_suffix(".json"), json.dumps({**run, "results": [r.model_dump() for r in results]}, default=str))
    typer.echo(f"wrote {out}")


@app.command()
def dashboard(
    out: Path = typer.Option(Path("reports/index.html")),
    db: Path = typer.Option(Path("arl.db")),
):
    """Static dashboard: history across versions plus a report page per run."""
    from .report import render_dashboard, render_report, write

    runs = []
    with Store(db) as store:
        for run_id, *_ in store.list_runs():
            run = store.get_run(run_id)
            page = f"runs/{run_id}.html"
            write(out.parent / page, render_report(run, store.load_results(run_id)))
            runs.append({**run, "report": page})
    write(out, render_dashboard(runs))
    typer.echo(f"wrote {out} ({len(runs)} runs)")


@app.command("ci-summary")
def ci_summary(
    summary: Path = typer.Option(..., help="Summary JSON from `arl run --json-out`."),
    comparison: Path | None = typer.Option(None, help="JSON from `arl compare --json-out`."),
    out: Path = typer.Option(Path("arl-comment.md")),
    report_url: str | None = typer.Option(None),
):
    """Markdown for a PR comment / GitHub job summary."""
    from .report import ci_markdown, write

    comp = json.loads(comparison.read_text()) if comparison and comparison.exists() else None
    write(out, ci_markdown(json.loads(summary.read_text()), comp, report_url))
    typer.echo(out.read_text(encoding="utf-8"))


@app.command()
def redteam(
    target: Path = typer.Option(..., help="Target YAML file."),
    seeds: str = typer.Option("builtin:library", help="Seed scenarios: paths and/or builtin packs, comma-separated."),
    out: Path = typer.Option(Path("scenarios/generated"), help="Where new failing variants are written."),
    rounds: int = typer.Option(2, min=1),
    per_seed: int = typer.Option(4, min=1, help="Mutations tried per surviving scenario per round."),
    seed: int = 0,
    generator_llm: str | None = typer.Option(None, help=f"Adds an LLM paraphrase mutator: {LLM_HELP}"),
    report_out: Path | None = typer.Option(None, help="Write the report JSON here."),
):
    """Mutate passing attack seeds; keep and save the variants that make the target fail."""
    from .redteam import generate

    sys.path.insert(0, str(Path.cwd()))
    tgt = _load_target(target)
    cfg = RunConfig(secrets=tgt.secrets)
    report = asyncio.run(generate(_build(tgt, target), suites.load(seeds), cfg, rounds, per_seed, seed,
                                  build_llm(generator_llm, role="generator")))
    folder = out / tgt.name
    folder.mkdir(parents=True, exist_ok=True)
    for s in report.new_failures:
        (folder / f"{s.id}.yaml").write_text(s.to_yaml(), encoding="utf-8", newline="\n")
    data = report.as_dict()
    typer.echo(f"seeds {data['seeds']} (already failing {data['seeds_already_failing']}), "
               f"variants tried {data['variants_tried']}, new failures {data['new_failures']} -> {folder}")
    for name, s in data["by_mutator"].items():
        typer.echo(f"  {name:<12} {s['failed']}/{s['tried']}")
    if report_out:
        report_out.write_text(json.dumps(data, indent=2))


@label_app.command("export")
def label_export(
    run_id: str = typer.Option(..., "--run"),
    out: Path = typer.Option(...),
    sample: int | None = typer.Option(None),
    db: Path = typer.Option(Path("arl.db")),
):
    """Export judged transcripts for human labeling."""
    with Store(db) as store:
        n = labels_mod.export(store, run_id, out, sample)
    typer.echo(f"exported {n} items to {out}")


@label_app.command("annotate")
def label_annotate(path: Path):
    """Label items interactively: y = pass, n = fail, s = skip, q = save and quit."""
    from .judges import RUBRICS

    items = labels_mod.read(path)
    total = len(items)
    try:
        for n, item in enumerate(items, 1):
            if item.get("human") is not None:
                continue
            typer.echo("\n" + "=" * 70 + f"\n[{n}/{total}] {item['scenario_id']}#{item['repeat']}  ({item['category']})")
            for m in item["transcript"]:
                typer.echo(f"  [{m['role']}] {m['content']}")
            for c in item.get("tool_calls", []):
                typer.echo(f"  (tool) {c['tool']} {c.get('args')} -> {c.get('error') or c.get('result')}")
            # The same question(s) the judge answered; its verdict is not shown, to avoid anchoring.
            for name in item.get("judge_reasons", {}):
                rubric = RUBRICS.get(name.removeprefix("judge:"))
                if rubric:
                    typer.echo(f"\n  QUESTION ({rubric.name}): {rubric.question}")
            answer = typer.prompt("pass? [y/n/s/q]", default="s").strip().lower()
            if answer == "q":
                break
            if answer in ("y", "n"):
                item["human"] = answer == "y"
    finally:
        labels_mod.write(path, items)
    done = sum(i.get("human") is not None for i in items)
    typer.echo(f"saved: {done}/{len(items)} labeled")


@label_app.command("agreement")
def label_agreement(path: Path, json_out: Path | None = typer.Option(None)):
    """Judge-human agreement on a labeled file."""
    report = labels_mod.agreement(labels_mod.read(path))
    typer.echo(json.dumps(report, indent=2))
    if json_out:
        json_out.write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    app()


@app.command()
def init(
    path: Path = typer.Argument(Path("."), help="Project root."),
    adapter: str = typer.Option("auto", help="auto (detect the agent) | http | python | langgraph | mcp"),
    ci: bool = typer.Option(True, help="Also write a GitHub Actions workflow."),
    force: bool = typer.Option(False, help="Overwrite existing files."),
):
    """Scaffold arl/target.yaml (configured for the agent found in the project), a starter scenario
    and a CI workflow."""
    from .detect import detect
    from .init import scaffold

    detected = None
    if adapter == "auto":
        found = detect(path)
        detected = found[0] if found else None
        if detected:
            typer.echo(f"Found {detected.framework} in {detected.file}"
                       + (f" ({detected.symbol})" if detected.symbol else "") + ".")
        else:
            typer.echo("No agent found; writing an HTTP template. See `arl detect` or pass --adapter.")
            adapter = "http"
    try:
        written = scaffold(path, adapter, force, ci, detected)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--adapter") from exc
    for f, status in written:
        typer.echo(f"  {status:<8} {f}")
    if detected and detected.note:
        typer.echo(f"\nTo do: {detected.note}")
    _print_canary(path)
    typer.echo("\nThen run:\n"
               "  arl check                                                   # seconds, after every change\n"
               "  arl run --target arl/target.yaml --suite builtin:standard   # minutes, before merging")


def _print_canary(path: Path) -> None:
    from .init import CANARY_LINE, read_canary

    canary = read_canary(path / "arl" / "target.yaml")
    if canary:
        typer.echo("\nAdd this sentence to your agent's system prompt (it's how leaks are detected):\n"
                   f"  {CANARY_LINE.format(canary=canary)}")


@app.command()
def canary(path: Path = typer.Argument(Path("."), help="Project root.")):
    """Show the system-prompt sentence with this project's canary (adds one to the target if missing)."""
    from .init import new_canary, read_canary

    target = path / "arl" / "target.yaml"
    if not target.is_file():
        raise typer.BadParameter("no arl/target.yaml; run `arl init` first", param_hint="path")
    if not read_canary(target):
        token = new_canary()
        before = _load_target(target).secrets
        text = target.read_text(encoding="utf-8")
        flow = re.search(r"^secrets:[ \t]*\[", text, re.M)
        block = re.search(r"^secrets:[ \t]*\n", text, re.M)
        if flow:
            text = text[:flow.end()] + f'"{token}", ' + text[flow.end():]
            text = text.replace(f'"{token}", ]', f'"{token}"]')
        elif block:
            text = text[:block.end()] + f'  - "{token}"\n' + text[block.end():]
        elif re.search(r"^secrets:", text, re.M):
            raise typer.BadParameter(f"{target}: can't add to this secrets: entry; add {token} to it by hand")
        else:
            text = text.rstrip() + f'\nsecrets: ["{token}"]\n'
        target.write_bytes(text.encode())
        after = _load_target(target).secrets
        if set(after) != set(before) | {token}:  # never lose a secret the user had configured
            raise typer.BadParameter(f"{target}: adding the canary would change existing secrets; add {token} by hand")
        typer.echo(f"Added canary {token} to {target}.")
    _print_canary(path)


@app.command()
def detect(path: Path = typer.Argument(Path("."), help="Project root."),
           as_json: bool = typer.Option(False, "--json", help="Machine-readable output.")):
    """Find the AI agent in a project (static scan) and show the target settings to use."""
    from .detect import detect as scan

    found = scan(path)
    if as_json:
        typer.echo(json.dumps([c.__dict__ for c in found], indent=2))
        return
    if not found:
        typer.echo("No agent found. Point a target at a function `respond(messages) -> str`, an HTTP chat "
                   "endpoint or an MCP server; see `arl init --help`.")
        return
    for i, c in enumerate(found[:8], 1):
        mark = "ready" if c.ready else "needs work"
        typer.echo(f"{i}. {c.framework}  [{mark}, confidence {c.confidence:.0%}]")
        typer.echo(f"   {c.file}" + (f"  {c.symbol}" if c.symbol else ""))
        typer.echo("   " + "  ".join(f"{k}: {v}" for k, v in c.target().items() if k not in ("name", "version")))
        if c.note:
            typer.echo(f"   to do: {c.note}")
    typer.echo("\n`arl init` configures the first one.")


@app.command("suites")
def list_suites():
    """List built-in scenario packs."""
    for name, rels in sorted(suites.BUILTIN.items()):
        n = sum(len(list((suites.builtin_root() / r).rglob("*.yaml"))) for r in rels)
        typer.echo(f"builtin:{name:<20} {n:>4} scenarios")


@app.command("mcp")
def mcp_cmd():
    """Serve the lab over MCP (stdio) for AI assistants. Needs the `mcp` extra."""
    try:
        from .mcp_server import main as serve
    except ImportError as exc:
        raise typer.BadParameter("install the MCP extra: pip install 'agent-reliability-lab[mcp]'") from exc
    serve()


@app.command("check")
def check_cmd(
    path: Path = typer.Argument(Path("."), help="Project root."),
    target: Path | None = typer.Option(None, help="Target YAML (default: arl/target.yaml)."),
    suite: str | None = typer.Option(None, help="Default: builtin:quick plus arl/scenarios."),
    force: bool = typer.Option(False, help="Run even if no files changed."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
    hook: str | None = typer.Option(None, help="Run as a Claude Code hook: 'stop'. Reads hook JSON on stdin."),
):
    """Fast, change-aware check while you build: reports only new failures and fixes.
    Exit code 1 when scenarios that passed before now fail."""
    from .quickcheck import hook_stop, render, run_check

    if hook == "stop":
        out = hook_stop(sys.stdin.read())
        if out:
            typer.echo(out)
        return
    if hook:
        raise typer.BadParameter("supported hooks: stop", param_hint="--hook")
    result = run_check(path, target, suite, force=force)
    typer.echo(json.dumps(result.to_dict(), indent=2) if as_json else render(result))
    if result.blocking:
        raise typer.Exit(1)


@app.command()
def coverage(
    suite: str = typer.Option("builtin:standard", help="Suite to analyse (packs and paths, comma-separated)."),
    target: Path | None = typer.Option(None, help="Target YAML: show what actually applies to this agent."),
    judge: bool = typer.Option(False, "--judge/--no-judge", help="Count judge-only scenarios as runnable."),
):
    """Which agent capabilities and OWASP risks a suite tests, and what is skipped for your agent and why."""
    from .taxonomy import AGENTIC, CAPABILITIES, OWASP_LLM
    from .taxonomy import coverage as cover

    scenarios = suites.load(suite)
    skipped: list[tuple[str, str]] = []
    if target:
        scenarios, skipped = suites.bind(scenarios, _load_target(target), judge=judge)
    cov = cover(scenarios)
    names = {"capability": CAPABILITIES, "owasp": OWASP_LLM, "agentic": AGENTIC}
    titles = {"capability": "Capabilities", "owasp": "OWASP Top 10 for LLM Apps (2025)",
              "agentic": "OWASP Agentic AI threats"}
    typer.echo(f"{len(scenarios)} scenarios will run" + (f", {len(skipped)} skipped" if target else ""))
    for kind in ("capability", "owasp", "agentic"):
        testable = [k for k in names[kind] if k not in cov[kind]["out_of_scope"]]
        typer.echo(f"\n{titles[kind]}: {len(cov[kind]['covered'])}/{len(testable)}")
        for key in names[kind]:
            n = cov[kind]["covered"].get(key)
            mark = f"{n:>4}" if n else ("  --" if key in testable else "  n/a")
            label = names[kind][key].split(":")[0]
            note = f"  (out of scope: {cov[kind]['out_of_scope'][key]})" if key in cov[kind]["out_of_scope"] else ""
            typer.echo(f"  {mark}  {key:<13} {label}{note}")
    if skipped:
        typer.echo("\nSkipped, by reason:")
        reasons: dict[str, int] = {}
        for _, why in skipped:
            reasons[why] = reasons.get(why, 0) + 1
        for why, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
            typer.echo(f"  {n:>4}  {why}")


@app.command("generate")
def generate_cmd(
    target: Path = typer.Option(Path("arl/target.yaml"), help="Target YAML."),
    profile: Path | None = typer.Option(None, help="Agent profile YAML (default: arl/profile.yaml if present)."),
    describe: str | None = typer.Option(None, help="What the agent does, if the target has no system prompt."),
    llm: str | None = typer.Option(None, help=f"LLM for profile extraction and attack writing: {LLM_HELP}"),
    per_risk: int = typer.Option(5, help="LLM-written attacks per OWASP risk."),
    out: Path = typer.Option(Path("arl/scenarios/generated"), help="Where to write scenarios."),
):
    """Write attacks specific to your agent (its domain, secrets, actions and rules), for review."""
    from .generate import Profile, extract_profile, generate, write

    tgt = _load_target(target)
    default_profile = target.parent / "profile.yaml"
    model = build_llm(llm, temperature=0.9, role="generator") if llm else None
    if profile or default_profile.is_file():
        prof = Profile.load(profile or default_profile)
        typer.echo(f"Profile: {profile or default_profile}")
    elif model is not None:
        text = describe or tgt.system_prompt
        if not text:
            raise typer.BadParameter("pass --describe 'what the agent does' (the target has no system_prompt)",
                                     param_hint="--describe")
        from .generate import scrub

        prof = scrub(asyncio.run(extract_profile(model, text)), tgt.secrets)
        default_profile.write_bytes(prof.dump().encode())
        typer.echo(f"Extracted a profile and saved it to {default_profile}; review it, then re-run to refine.")
    else:
        default_profile.write_bytes(Profile(domain="(what your agent does)", protected=["system prompt"],
                                            actions=[], rules=[]).dump().encode())
        raise typer.BadParameter(f"no profile: fill in {default_profile} (written as a template), or pass "
                                 "--llm to extract one", param_hint="--profile")
    existing = suites.load("builtin:deep") + (suites.load(str(out)) if out.is_dir() else [])
    scenarios = asyncio.run(generate(tgt, prof, model, per_risk, existing))
    paths = write(scenarios, out)
    by_kind: dict[str, int] = {}
    for s in scenarios:
        kind = s.id.split("-")[1]
        by_kind[kind] = by_kind.get(kind, 0) + 1
    typer.echo(f"Wrote {len(paths)} new scenarios to {out} ("
               + ", ".join(f"{n} {k}" for k, n in sorted(by_kind.items())) + ").")
    judge_only = sum(s.criteria.judge_only for s in scenarios)
    if judge_only:
        typer.echo(f"{judge_only} need a judge to grade (--judge-llm); the rest use deterministic checks.")
    typer.echo(f"Run them: arl run --target {target} --suite {out}")


@app.command()
def ui(
    db: list[Path] = typer.Option([], "--db", help="Result database(s). Default: .arl/arl.db and arl.db here."),
    port: int = typer.Option(8765, help="Port on 127.0.0.1."),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open the dashboard in a browser."),
    export: Path | None = typer.Option(None, help="Write a self-contained read-only copy to this folder instead."),
    export_runs: int = typer.Option(20, help="With --export: latest runs per agent to include (0 = all)."),
):
    """Dashboard: verdicts, findings with the exact attack and reply, coverage, replays and comparisons."""
    from .ui.data import Data, discover
    from .ui.server import export as export_site
    from .ui.server import serve

    dbs = discover([str(p) for p in db] or None)
    if not dbs:
        raise typer.BadParameter("no result database found; run `arl check` or `arl run` first, or pass --db",
                                 param_hint="--db")
    _check_dbs(dbs)
    data = Data(dbs)
    if export:
        index = export_site(data, export, export_runs or None)
        typer.echo(f"Exported to {index} (latest {export_runs or 'all'} runs per agent)")
        return
    server = serve(data, port=port, open_browser=open_browser)
    typer.echo(f"Dashboard on http://127.0.0.1:{server.server_port}/  ({', '.join(map(str, dbs))}). Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
