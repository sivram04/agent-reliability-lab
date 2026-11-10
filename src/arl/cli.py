"""`arl` command line."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

import typer

from . import labels as labels_mod
from .adapters import build_agent
from .cassette import Cassette
from .llm import build_llm
from .models import RunResult, Scenario, Target
from .runner import RunConfig, run_suite, summarize
from .stats import compare as compare_runs
from .store import Store
from .tracing import setup_otel, shutdown_otel

app = typer.Typer(help="Agent Reliability Lab: chaos engineering for AI agents.")
label_app = typer.Typer(help="Human labels and judge-human agreement.")
app.add_typer(label_app, name="label")

LLM_HELP = "'openai' (ARL_LLM_* env vars) or 'python:module:fn'."


def _pct(x) -> str:
    return "n/a" if x is None else f"{x:.0%}"


@app.command()
def run(
    target: Path = typer.Option(..., help="Target YAML file."),
    suite: Optional[Path] = typer.Option(None, help="Scenario file or directory. Omit for an empty suite."),
    repeats: int = typer.Option(1, min=1),
    seed: int = 0,
    concurrency: int = typer.Option(4, min=1),
    db: Path = typer.Option(Path("arl.db"), help="SQLite results file."),
    min_pass_rate: float = typer.Option(0.0, help="Exit 1 if the pass rate falls below this."),
    json_out: Optional[Path] = typer.Option(None, help="Write the summary JSON here."),
    results_out: Optional[Path] = typer.Option(None, help="Write full results JSON here (a baseline for compare)."),
    cassette: Optional[Path] = typer.Option(None, help="Cassette file for record/replay."),
    record_mode: str = typer.Option("off", help="off | record | replay (needs --cassette)."),
    otel: Optional[str] = typer.Option(None, help="Export traces: console | otlp."),
    user_llm: Optional[str] = typer.Option(None, help=f"Simulated-user LLM: {LLM_HELP}"),
    judge_llm: Optional[str] = typer.Option(None, help=f"Judge LLM: {LLM_HELP}"),
):
    """Run a scenario suite against a target agent."""
    sys.path.insert(0, str(Path.cwd()))
    if record_mode != "off" and not cassette:
        raise typer.BadParameter("--record-mode needs --cassette")
    setup_otel(otel)
    tgt = Target.load(target)
    scenarios = Scenario.load_dir(suite) if suite else []
    tape = Cassette(cassette, record_mode) if cassette else None
    replay = record_mode == "replay"
    # Replay never builds the real agent or LLMs, so it works offline.
    agent = None if replay else build_agent(tgt)
    user = None if replay else build_llm(user_llm)
    judge = None if replay else build_llm(judge_llm, temperature=0.0)  # repeatable verdicts
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
    run_id = Store(db).save_run(tgt, results, summary, str(suite or ""))

    typer.echo(f"run {run_id}  target={tgt.name}@{tgt.version}  scenarios={len(scenarios)}  repeats={repeats}")
    for r in results:
        if not r.passed:
            failed = [c.name for c in r.checks if not c.passed]
            typer.echo(f"  FAIL {r.scenario_id}#{r.repeat}: {r.error or ', '.join(failed)}")
    lo, hi = summary["pass_rate_ci95"]
    typer.echo(f"pass rate {summary['pass_rate']:.0%} ({summary['passed']}/{summary['runs']}), 95% CI {lo:.0%}-{hi:.0%}")
    for cat, rate in summary["by_category"].items():
        typer.echo(f"  {cat:<20} {rate:.0%}")
    typer.echo(
        f"recovery {_pct(summary['recovery_rate'])}  safety violations {_pct(summary['safety_violation_rate'])}  "
        f"loops {_pct(summary['loop_rate'])}  hallucinations {_pct(summary['hallucination_rate'])}  "
        f"p95 {summary['p95_latency_s']:.2f}s"
    )
    if json_out:
        json_out.write_text(json.dumps({"run_id": run_id, "target": tgt.name, "version": tgt.version, **summary},
                                       indent=2))
    if results_out:
        _write_results(results_out, results)
    if summary["pass_rate"] < min_pass_rate:
        raise typer.Exit(1)


def _write_results(path: Path, results: list[RunResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([r.model_dump() for r in results], default=str), encoding="utf-8")


def _load_results(spec: str, db: Path) -> list[RunResult]:
    """A run id in the database, or a results JSON file from --results-out."""
    path = Path(spec)
    if path.suffix == ".json" and path.exists():
        return [RunResult.model_validate(r) for r in json.loads(path.read_text(encoding="utf-8"))]
    return Store(db).load_results(spec)


@app.command()
def runs(db: Path = typer.Option(Path("arl.db"))):
    """List past runs."""
    for run_id, name, version, created, summary in Store(db).list_runs():
        s = json.loads(summary)
        typer.echo(f"{run_id}  {created[:19]}  {name}@{version}  {s['pass_rate']:.0%} of {s['runs']}")


@app.command()
def compare(
    base: str = typer.Argument(..., help="Baseline run id or results JSON."),
    new: str = typer.Argument(..., help="Candidate run id or results JSON."),
    db: Path = typer.Option(Path("arl.db")),
    alpha: float = typer.Option(0.05, help="Significance level."),
    max_drop: float = typer.Option(0.0, help="Ignore drops smaller than this (absolute pass rate)."),
    json_out: Optional[Path] = typer.Option(None),
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
    baseline: Optional[str] = typer.Option(None, help="Baseline run id or results JSON, for a comparison section."),
    db: Path = typer.Option(Path("arl.db")),
):
    """HTML report card with failing traces you can replay step by step."""
    from .report import render_report, write

    store = Store(db)
    if run_id == "latest":
        run_id = store.list_runs()[0][0]
    run = store.get_run(run_id)
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

    store = Store(db)
    runs = []
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
    comparison: Optional[Path] = typer.Option(None, help="JSON from `arl compare --json-out`."),
    out: Path = typer.Option(Path("arl-comment.md")),
    report_url: Optional[str] = typer.Option(None),
):
    """Markdown for a PR comment / GitHub job summary."""
    from .report import ci_markdown, write

    comp = json.loads(comparison.read_text()) if comparison and comparison.exists() else None
    write(out, ci_markdown(json.loads(summary.read_text()), comp, report_url))
    typer.echo(out.read_text(encoding="utf-8"))


@app.command()
def redteam(
    target: Path = typer.Option(..., help="Target YAML file."),
    seeds: Path = typer.Option(Path("scenarios/library"), help="Seed scenarios."),
    out: Path = typer.Option(Path("scenarios/generated"), help="Where new failing variants are written."),
    rounds: int = typer.Option(2, min=1),
    per_seed: int = typer.Option(4, min=1, help="Mutations tried per surviving scenario per round."),
    seed: int = 0,
    generator_llm: Optional[str] = typer.Option(None, help=f"Adds an LLM paraphrase mutator: {LLM_HELP}"),
    report_out: Optional[Path] = typer.Option(None, help="Write the report JSON here."),
):
    """Mutate passing attack seeds; keep and save the variants that make the target fail."""
    from .redteam import generate

    sys.path.insert(0, str(Path.cwd()))
    tgt = Target.load(target)
    cfg = RunConfig(secrets=tgt.secrets)
    report = asyncio.run(generate(build_agent(tgt), Scenario.load_dir(seeds), cfg, rounds, per_seed, seed,
                                  build_llm(generator_llm)))
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
    sample: Optional[int] = typer.Option(None),
    db: Path = typer.Option(Path("arl.db")),
):
    """Export judged transcripts for human labeling."""
    n = labels_mod.export(Store(db), run_id, out, sample)
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
def label_agreement(path: Path, json_out: Optional[Path] = typer.Option(None)):
    """Judge-human agreement on a labeled file."""
    report = labels_mod.agreement(labels_mod.read(path))
    typer.echo(json.dumps(report, indent=2))
    if json_out:
        json_out.write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    app()
