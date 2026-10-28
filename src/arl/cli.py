"""`arl` command line."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

import typer

from .adapters import build_agent
from .cassette import Cassette
from .llm import build_llm
from .models import Scenario, Target
from .runner import RunConfig, run_suite, summarize
from .store import Store
from .tracing import setup_otel, shutdown_otel

app = typer.Typer(help="Agent Reliability Lab: chaos engineering for AI agents.")


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
    cassette: Optional[Path] = typer.Option(None, help="Cassette file for record/replay."),
    record_mode: str = typer.Option("off", help="off | record | replay (needs --cassette)."),
    otel: Optional[str] = typer.Option(None, help="Export traces: console | otlp."),
    user_llm: Optional[str] = typer.Option(
        None, help="Simulated-user LLM: 'openai' (ARL_LLM_* env) or 'python:module:fn'."
    ),
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
    if tape:
        agent = tape.wrap(agent)
        if user_llm:
            user = tape.wrap(user, "user")
    cfg = RunConfig(repeats=repeats, seed=seed, concurrency=concurrency, user_llm=user, secrets=tgt.secrets)
    results = asyncio.run(run_suite(agent, scenarios, cfg=cfg))
    if tape:
        tape.save()
    shutdown_otel()
    summary = summarize(results)
    run_id = Store(db).save_run(tgt, results, summary, str(suite or ""))

    typer.echo(f"run {run_id}  target={tgt.name}@{tgt.version}  scenarios={len(scenarios)}")
    for r in results:
        if not r.passed:
            failed = [c.name for c in r.checks if not c.passed]
            typer.echo(f"  FAIL {r.scenario_id}#{r.repeat}: {r.error or ', '.join(failed)}")
    typer.echo(f"pass rate {summary['pass_rate']:.0%} ({summary['passed']}/{summary['runs']})")
    for cat, rate in summary["by_category"].items():
        typer.echo(f"  {cat:<20} {rate:.0%}")
    if json_out:
        json_out.write_text(json.dumps({"run_id": run_id, **summary}, indent=2))
    if summary["pass_rate"] < min_pass_rate:
        raise typer.Exit(1)


@app.command()
def runs(db: Path = typer.Option(Path("arl.db"))):
    """List past runs."""
    for run_id, name, version, created, summary in Store(db).list_runs():
        s = json.loads(summary)
        typer.echo(f"{run_id}  {created[:19]}  {name}@{version}  {s['pass_rate']:.0%} of {s['runs']}")


if __name__ == "__main__":
    app()
