"""`arl mcp`: the lab as an MCP server, so AI assistants (Claude, Cursor, VS Code) can run
reliability suites on an agent and explain the failures.

Add to an MCP client config:
    {"mcpServers": {"arl": {"command": "arl", "args": ["mcp"]}}}

Tools: check, detect_agent, generate_attacks, list_suites, init_project, run_suite, list_runs, run_failures, compare_runs.
Target secrets are redacted in everything returned to the client.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import suites
from .adapters import build_agent
from .explain import explain, headline
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


def detect_agent(path: str = ".") -> list[dict]:
    """Find the AI agent in a project by static scan: framework, file, target settings, confidence,
    and what still has to be done (for example a wrapper function). Call before init_project."""
    from .detect import detect

    return [c.__dict__ | {"ready": c.ready} for c in detect(Path(path))[:8]]


def init_project(path: str = ".", adapter: str = "auto", candidate: int = 0) -> dict:
    """Scaffold arl/target.yaml, a starter scenario and a CI workflow. Never overwrites files.
    adapter "auto" configures the target from detect_agent's result number `candidate` (0 = best)."""
    from .detect import detect
    from .init import scaffold

    detected = None
    if adapter == "auto":
        found = detect(Path(path))
        detected = found[candidate] if len(found) > candidate else None
        adapter = "http" if detected is None else adapter
    files = [f"{status} {p}" for p, status in scaffold(Path(path), adapter, detected=detected)]
    from .init import CANARY_LINE, read_canary

    canary = read_canary(Path(path) / "arl" / "target.yaml")
    return {"files": files, "detected": detected.__dict__ if detected else None,
            "canary_sentence": CANARY_LINE.format(canary=canary) if canary else None,
            "todo": detected.note if detected else "No agent found: edit arl/target.yaml by hand."}


async def run_suite(target: str, suite: str = "builtin:smoke", repeats: int = 1, db: str = "arl.db",
                    user_llm: str | None = None, judge_llm: str | None = None, max_failures: int = 10) -> dict:
    """Run scenarios against the agent described by a target YAML file.

    suite: paths and/or builtin packs, comma-separated (e.g. "builtin:safety,arl/scenarios").
    user_llm / judge_llm: optional LLM specs such as "gemini:gemini-3.5-flash-lite" or "ollama:llama3.1".
    Returns the run id, summary metrics and up to max_failures failing conversations.
    """
    tgt = Target.load(target)
    load_prices(tgt.prices)
    scenarios, skipped = suites.bind(suites.load(suite), tgt, judge=bool(judge_llm))
    cfg = RunConfig(repeats=repeats, secrets=tgt.secrets, user_llm=build_llm(user_llm, role="user"),
                    judge_llm=build_llm(judge_llm, temperature=0.0, role="judge"))
    results = await _run_suite(build_agent(tgt), scenarios, cfg=cfg)
    summary = summarize(results)
    store = Store(db)
    try:
        run_id = store.save_run(tgt, results, summary, suite, source="mcp")
    finally:
        store.close()
    return _redact({"run_id": run_id, "target": f"{tgt.name}@{tgt.version}", "summary": summary,
                    "headline": headline(found := explain(results, tgt.secrets), len(scenarios)),
                    "findings": [f.to_dict() for f in found],
                    "failures": _failures(results, max_failures),
                    "skipped": [{"scenario": sid, "reason": why} for sid, why in skipped]}, tgt.secrets)


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


def check(path: str = ".", force: bool = False) -> dict:
    """Fast change-aware check of the agent in this project (builtin:quick plus arl/scenarios, no LLM cost).
    Returns status (pass | failing | regressed | unchanged | no_target | unreachable | error), new failures
    with the attack and the agent's reply, and scenarios fixed since the last check. Use after editing an agent."""
    from .quickcheck import run_check

    return run_check(Path(path), force=force).to_dict()


async def generate_attacks(target: str = "arl/target.yaml", llm: str | None = None, per_risk: int = 5,
                           out: str = "arl/scenarios/generated") -> dict:
    """Write attacks specific to this agent (its domain, protected data, actions and rules) into `out` for
    review. Uses arl/profile.yaml next to the target if present; otherwise needs `llm` (e.g.
    "gemini:gemini-3.5-flash-lite" or "ollama:llama3.1") to extract a profile from the system prompt.
    Re-running adds only new attacks. Secret values are never put in prompts or files."""
    from .generate import Profile, extract_profile, generate, scrub, write

    if not Path(target).is_file():
        return {"error": f"target file not found: {target}. Run init_project first."}
    tgt = Target.load(target)
    profile_path = Path(target).parent / "profile.yaml"
    model = build_llm(llm, temperature=0.9, role="generator") if llm else None
    if profile_path.is_file():
        prof = Profile.load(profile_path)
    elif model is not None and tgt.system_prompt:
        prof = scrub(await extract_profile(model, tgt.system_prompt), tgt.secrets)
        profile_path.write_bytes(prof.dump().encode())
    else:
        return {"error": f"no profile: write {profile_path} (domain, protected, actions, rules) or pass llm "
                         "with a target that has a system_prompt"}
    out_dir = Path(out)
    existing = suites.load("builtin:deep") + (suites.load(str(out_dir)) if out_dir.is_dir() else [])
    scenarios = await generate(tgt, prof, model, per_risk, existing)
    write(scenarios, out_dir)
    return {"written": len(scenarios), "out": str(out_dir), "profile": str(profile_path),
            "judge_only": sum(s.criteria.judge_only for s in scenarios),
            "examples": [s.turns[0] for s in scenarios[:5]]}


TOOLS = [check, detect_agent, generate_attacks, list_suites, init_project, run_suite, list_runs, run_failures, compare_runs]


def build_server():
    from mcp.server.mcpserver import MCPServer

    server = MCPServer("agent-reliability-lab", instructions=__doc__)
    for fn in TOOLS:
        server.tool()(fn)
    return server


def main() -> None:
    build_server().run()
