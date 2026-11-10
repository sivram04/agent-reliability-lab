"""`arl check`: a fast, change-aware reliability check for use while building an agent.

Designed to run in the background (editor hooks, pre-commit, watch loops):
- does nothing outside agent projects (no target file), so it is safe to enable everywhere;
- skips the run when no watched file changed since the last check;
- deterministic checks only, one repeat: seconds, no LLM cost;
- reports only what changed versus the previous run: new failures and fixes.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from . import suites
from .adapters import build_agent
from .models import RunResult, Target
from .runner import RunConfig, run_suite, summarize
from .store import Store

STATE_DIR = ".arl"
TARGET_CANDIDATES = ("arl/target.yaml", "arl.yaml", ".arl/target.yaml")
WATCH = ("*.py", "*.ts", "*.js", "*.mjs", "*.yaml", "*.yml", "*.json", "*.toml", "*.md", "*.txt", "*.j2", "*.prompt")
SKIP_DIRS = {".git", ".arl", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "dist", "build", "reports"}
MAX_FILES = 5000


@dataclass
class CheckResult:
    status: str  # no_target | unchanged | pass | regressed | failing | unreachable | error
    message: str
    run_id: str | None = None
    pass_rate: float | None = None
    new_failures: list[dict] = field(default_factory=list)
    fixed: list[str] = field(default_factory=list)
    still_failing: list[str] = field(default_factory=list)

    @property
    def blocking(self) -> bool:
        """Worth interrupting the developer (or the coding agent) about."""
        return self.status == "regressed"

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__} | {"blocking": self.blocking}


def find_target(root: Path) -> Path | None:
    return next((root / c for c in TARGET_CANDIDATES if (root / c).is_file()), None)


def fingerprint(root: Path) -> str:
    """Hash of watched files' paths, sizes and mtimes: cheap change detection without reading files."""
    h = hashlib.sha256()
    n = 0
    stack = [root]
    while stack and n < MAX_FILES:
        d = stack.pop()
        try:
            entries = sorted(d.iterdir())
        except OSError:
            continue
        for p in entries:
            if p.is_dir():
                if p.name not in SKIP_DIRS and not p.name.startswith("."):
                    stack.append(p)
            elif any(p.match(g) for g in WATCH):
                st = p.stat()
                h.update(f"{p.relative_to(root)}|{st.st_size}|{st.st_mtime_ns}\n".encode())
                n += 1
    return h.hexdigest()


def _state(root: Path) -> dict:
    try:
        return json.loads((root / STATE_DIR / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(root: Path, state: dict) -> None:
    d = root / STATE_DIR
    d.mkdir(exist_ok=True)
    (d / ".gitignore").write_text("*\n")  # results and transcripts stay out of git
    (d / "state.json").write_text(json.dumps(state, indent=2))


def default_suite(root: Path) -> str:
    own = root / "arl" / "scenarios"
    return "builtin:quick" + (f",{own}" if own.is_dir() and any(own.rglob("*.yaml")) else "")


def _keys(results: list[RunResult]) -> dict[str, RunResult]:
    return {f"{r.scenario_id}#{r.repeat}": r for r in results}


def _describe(r: RunResult, secrets: list[str]) -> dict:
    failed = [c for c in r.checks if not c.passed]
    last_reply = next((m["content"] for m in reversed(r.transcript) if m["role"] == "assistant"), "")
    text = json.dumps({
        "scenario": r.scenario_id, "category": r.category, "error": r.error,
        "failed_checks": [f"{c.name}{': ' + c.detail if c.detail else ''}" for c in failed],
        "last_user": next((m["content"] for m in reversed(r.transcript) if m["role"] == "user"), "")[:300],
        "last_reply": last_reply[:300],
    })
    for s in secrets:
        if s:
            text = text.replace(s, "[REDACTED]")
    return json.loads(text)


def run_check(root: Path = Path("."), target: Path | None = None, suite: str | None = None,
              db: Path | None = None, force: bool = False) -> CheckResult:
    root = root.resolve()
    target = target or find_target(root)
    if target is None:
        return CheckResult("no_target", "No arl/target.yaml here; nothing to check. Run `arl init` to start.")
    state = _state(root)
    fp = fingerprint(root)
    if not force and state.get("fingerprint") == fp:
        return CheckResult("unchanged", "No agent files changed since the last check.", state.get("run_id"),
                           state.get("pass_rate"))
    try:
        tgt = Target.load(target)
        scenarios = suites.load(suite or default_suite(root), tgt)
        results = asyncio.run(run_suite(build_agent(tgt), scenarios, cfg=RunConfig(secrets=tgt.secrets)))
    except Exception as exc:  # setup problems are reported, never raised into a hook
        return CheckResult("error", f"Could not run the check: {type(exc).__name__}: {exc}")

    unreachable = [r for r in results if r.error and any(
        k in r.error for k in ("ConnectionRefused", "URLError", "actively refused", "Connection refused"))]
    if results and len(unreachable) == len(results):
        return CheckResult("unreachable", f"Agent not reachable at {tgt.url}. Start it, then the check runs again.")

    summary = summarize(results)
    (root / STATE_DIR).mkdir(exist_ok=True)
    store = Store(db or root / STATE_DIR / "arl.db")
    try:
        prev_id = store.latest_run(tgt.name)
        prev = _keys(store.load_results(prev_id)) if prev_id else {}
        run_id = store.save_run(tgt, results, summary, suite or default_suite(root), source="check")
    finally:
        store.close()

    now = _keys(results)
    failing = {k for k, r in now.items() if not r.passed}
    was_failing = {k for k, r in prev.items() if not r.passed}
    new = sorted(failing - was_failing) if prev else sorted(failing)
    fixed = sorted(k for k in was_failing - failing if k in now)
    out = CheckResult("pass", "", run_id, summary["pass_rate"],
                      [_describe(now[k], tgt.secrets) for k in new], fixed, sorted(failing & was_failing))
    if new and prev:
        out.status = "regressed"
        out.message = f"{len(new)} scenario(s) that passed before now fail ({summary['pass_rate']:.0%} pass)."
    elif failing:
        out.status = "failing"
        out.message = f"{len(failing)} of {len(results)} scenarios fail ({summary['pass_rate']:.0%} pass)."
    else:
        out.message = f"All {len(results)} scenarios pass."
    if fixed:
        out.message += f" Fixed: {len(fixed)}."
    _save_state(root, {"fingerprint": fp, "run_id": run_id, "pass_rate": summary["pass_rate"], "status": out.status})
    return out


def render(result: CheckResult, limit: int = 5) -> str:
    lines = [f"[arl] {result.message}"]
    for f in result.new_failures[:limit]:
        lines.append(f"  NEW FAIL {f['scenario']} ({f['category']}): {'; '.join(f['failed_checks']) or f['error']}")
        if f["last_user"]:
            lines.append(f"    user:  {f['last_user']}")
        if f["last_reply"]:
            lines.append(f"    agent: {f['last_reply']}")
    if len(result.new_failures) > limit:
        lines.append(f"  ... and {len(result.new_failures) - limit} more")
    if result.fixed:
        lines.append(f"  fixed: {', '.join(result.fixed[:limit])}")
    if result.run_id and result.status not in ("unchanged",):
        lines.append(f"  details: arl ui  (run {result.run_id})")
    return "\n".join(lines)



def hook_stop(stdin: str) -> str:
    """Claude Code Stop hook. When the coding agent finishes a turn that changed the agent under test,
    run the check; if something that passed now fails, block the stop so it fixes the regression first.

    Returns JSON for stdout (or "" to stay silent). Never raises: a broken check must not break the editor.
    """
    try:
        event = json.loads(stdin or "{}")
    except ValueError:
        event = {}
    if event.get("stop_hook_active"):
        return ""  # already continuing because of us: avoid loops, let the next turn's check speak
    try:
        result = run_check(Path(event.get("cwd") or "."))
    except Exception:  # noqa: BLE001
        return ""
    if result.blocking:
        reason = (render(result) + "\n\nThese reliability scenarios passed before your last changes. "
                  "Fix the agent so they pass again (do not weaken the scenarios), then finish. "
                  "Use the arl MCP tools (run_failures) for full conversations.")
        return json.dumps({"decision": "block", "reason": reason})
    if result.status in ("failing", "unreachable", "error"):
        return json.dumps({"systemMessage": render(result)})  # shown to the user, does not block
    return ""
