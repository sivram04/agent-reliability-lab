"""`arl mcp`: the lab as an MCP server, so AI assistants (Claude, Cursor, VS Code) can run
reliability suites on an agent and explain the failures.

Add to an MCP client config:
    {"mcpServers": {"arl": {"command": "arl", "args": ["mcp"]}}}

Tools: list_suites, init_project, run_suite, list_runs, run_failures, compare_runs.
Target secrets are redacted in everything returned to the client.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import suites
from .adapters import build_agent
from .llm import build_llm
from .models import RunResult, Target
from .runner import RunConfig, summarize
from .runner import run_suite as _run_suite
from .stats import compare as _compare
from .store import Store
from .usage import load_prices


def _redact(obj, secrets: list[str]):
    pats = [re.compile(re.escape(s), re.IGNORECASE) for s in sorted(secrets, key=len, reverse=True) if s]
    text = json.dumps(obj, default=str)
    for p in pats:
        text = p.sub("[REDACTED]", text)
    return json.loads(text)


def _failures(results: list[RunResult], limit: int) -> list[dict]:
    out = []
    for r in results:
        if r.passed:
            continue
        out.append({
            "scenario": f"{r.scenario_id}#{r.repeat}", "category": r.category, "error": r.error,
            "failed_checks": [{"name": c.name, "detail": c.detail} for c in r.checks if not c.passed],
            "transcript": r.transcript[-6:],
        })
        if len(out) >= limit:
            break
    return out


def _results(spec: str, db: str) -> list[RunResult]:
    path = Path(spec)
    if path.suffix == ".json" and path.exists():
        return [RunResult.model_validate(r) for r in json.loads(path.read_text(encoding="utf-8"))]
    store = Store(db)
    try:
        return store.load_results(spec)
    finally:
        store.close()


def list_suites() -> dict[str, int]:
    """Built-in scenario packs and how many scenarios each has. Combine packs and paths with commas."""
    return {f"builtin:{name}": len(suites.load(f"builtin:{name}")) for name in sorted(suites.BUILTIN)}


def init_project(path: str = ".", adapter: str = "http") -> list[str]:
    """Scaffold arl/target.yaml, a starter scenario and a CI workflow. Never overwrites files."""
    from .init import scaffold

    return [f"{status} {p}" for p, status in scaffold(Path(path), adapter)]


async def run_suite(target: str, suite: str = "builtin:smoke", repeats: int = 1, db: str = "arl.db",
                    user_llm: str | None = None, judge_llm: str | None = None, max_failures: int = 10) -> dict:
    """Run scenarios against the agent described by a target YAML file.

    suite: paths and/or builtin packs, comma-separated (e.g. "builtin:safety,arl/scenarios").
    user_llm / judge_llm: optional LLM specs such as "gemini:gemini-3.5-flash-lite" or "ollama:llama3.1".
    Returns the run id, summary metrics and up to max_failures failing conversations.
    """
    tgt = Target.load(target)
    load_prices(tgt.prices)
    scenarios = suites.load(suite)
    cfg = RunConfig(repeats=repeats, secrets=tgt.secrets, user_llm=build_llm(user_llm, role="user"),
                    judge_llm=build_llm(judge_llm, temperature=0.0, role="judge"))
    results = await _run_suite(build_agent(tgt), scenarios, cfg=cfg)
    summary = summarize(results)
    store = Store(db)
    try:
        run_id = store.save_run(tgt, results, summary, suite)
    finally:
        store.close()
    return _redact({"run_id": run_id, "target": f"{tgt.name}@{tgt.version}", "summary": summary,
                    "failures": _failures(results, max_failures)}, tgt.secrets)


def list_runs(db: str = "arl.db", limit: int = 20) -> list[dict]:
    """Most recent runs with pass rates."""
    store = Store(db)
    try:
        rows = store.list_runs()[:limit]
    finally:
        store.close()
    return [{"run_id": rid, "target": f"{name}@{version}", "created": created[:19],
             "pass_rate": json.loads(summary)["pass_rate"], "runs": json.loads(summary)["runs"]}
            for rid, name, version, created, summary in rows]


def run_failures(run_id: str, db: str = "arl.db", limit: int = 20, target: str | None = None) -> list[dict]:
    """Failing conversations of a past run, with the checks that failed. Pass the target YAML to redact its secrets."""
    secrets = Target.load(target).secrets if target else []
    return _redact(_failures(_results(run_id, db), limit), secrets)


def compare_runs(base: str, new: str, db: str = "arl.db", alpha: float = 0.05) -> dict:
    """Statistical comparison of two runs (run ids or results JSON files). regression=true means block the deploy."""
    return _compare(_results(base, db), _results(new, db), alpha)


TOOLS = [list_suites, init_project, run_suite, list_runs, run_failures, compare_runs]


def build_server():
    from mcp.server.mcpserver import MCPServer

    server = MCPServer("agent-reliability-lab", instructions=__doc__)
    for fn in TOOLS:
        server.tool()(fn)
    return server


def main() -> None:
    build_server().run()
