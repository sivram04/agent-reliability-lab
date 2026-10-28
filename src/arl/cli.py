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
    judge = None if replay else build_llm(judge_llm)
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
    items = labels_mod.read(path)
    try:
        for item in items:
            if item.get("human") is not None:
                continue
            typer.echo("\n" + "=" * 70 + f"\n{item['scenario_id']}#{item['repeat']}  ({item['category']})")
            for m in item["transcript"]:
                typer.echo(f"  [{m['role']}] {m['content']}")
            for c in item.get("tool_calls", []):
                typer.echo(f"  (tool) {c['tool']} {c.get('args')} -> {c.get('error') or c.get('result')}")
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
