"""Reports (F9), dashboard (F11), and CI summaries (F10)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from .models import RunResult
from .runner import summarize
from .stats import compare, wilson_ci

_env = Environment(loader=PackageLoader("arl", "templates"), autoescape=select_autoescape(["html"]))
_env.filters["pct"] = lambda v: "n/a" if v is None else f"{v:.0%}"
_env.filters["tojson_pretty"] = lambda v: json.dumps(v, indent=2, default=str)

HEADLINE = [
    ("pass_rate", "Pass rate"), ("injection_resistance", "Injection resistance"),
    ("safety_violation_rate", "Safety violations"), ("recovery_rate", "Recovery after faults"),
    ("hallucination_rate", "Hallucinations"), ("loop_rate", "Runaway loops"), ("crash_rate", "Crashes"),
]
LOWER_IS_BETTER = {"safety_violation_rate", "hallucination_rate", "loop_rate", "crash_rate"}


def _category_rows(results: list[RunResult]) -> list[dict]:
    rows = []
    for cat in sorted({r.category for r in results}):
        rs = [r for r in results if r.category == cat]
        k = sum(r.passed for r in rs)
        lo, hi = wilson_ci(k, len(rs))
        rows.append({"category": cat, "passed": k, "runs": len(rs), "rate": k / len(rs), "lo": lo, "hi": hi})
    return rows


def _steps(r: RunResult) -> list[dict]:
    """Interleave transcript turns and tool calls into a replayable step list."""
    def tool_steps(turn: int) -> list[dict]:
        return [{"kind": "tool", "tool": c["tool"], "args": c.get("args"), "fault": c.get("fault"),
                 "outcome": c.get("error") or c.get("result")}
                for c in r.tool_calls if c.get("turn", 0) == turn]

    steps, turn = [], -1
    for m in r.transcript:
        if m["role"] == "user":
            turn += 1
            steps.append({"kind": "user", "content": m["content"]})
            steps += tool_steps(turn)
        else:
            steps.append({"kind": "assistant", "content": m["content"]})
    if r.error:
        steps.append({"kind": "error", "content": r.error})
    return steps


def render_report(run: dict, results: list[RunResult], baseline: list[RunResult] | None = None) -> str:
    summary = summarize(results)
    failures = sorted((r for r in results if not r.passed), key=lambda r: (r.category, r.scenario_id, r.repeat))
    return _env.get_template("report.html.j2").render(
        run=run, summary=summary, headline=HEADLINE, lower_is_better=LOWER_IS_BETTER,
        categories=_category_rows(results),
        failures=[{"r": r, "failed": [c for c in r.checks if not c.passed], "steps": _steps(r)} for r in failures],
        comparison=compare(baseline, results) if baseline else None,
        generated=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
    )


def render_dashboard(runs: list[dict]) -> str:
    """runs: dicts with id, target, version, created_at, summary, report (relative link)."""
    by_target: dict[str, list[dict]] = {}
    for run in sorted(runs, key=lambda r: r["created_at"]):
        by_target.setdefault(run["target"], []).append(run)
    return _env.get_template("dashboard.html.j2").render(
        by_target=by_target, runs=sorted(runs, key=lambda r: r["created_at"], reverse=True),
        generated=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
    )


def ci_markdown(summary: dict, comparison: dict | None, report_url: str | None = None) -> str:
    lines = ["## Agent reliability report", ""]
    status = "**Blocked: significant regression**" if comparison and comparison["regression"] else "**Passed**"
    lines += [f"{status} - `{summary.get('target', '')}@{summary.get('version', '')}`, {summary['runs']} runs", ""]
    lines += ["| Metric | Value |", "|---|---|"]
    for key, label in HEADLINE:
        v = summary.get(key)
        lines.append(f"| {label} | {'n/a' if v is None else f'{v:.0%}'} |")
    if comparison:
        lines += ["", "### Compared with baseline", "", "| Metric | Base | New | Delta | p |", "|---|---|---|---|---|"]
        for row in comparison["rows"]:
            if row["metric"].startswith("latency"):
                continue
            flag = " :x:" if row["regression"] else ""
            lines.append(f"| {row['metric']}{flag} | {row['base']:.0%} | {row['new']:.0%} | "
                         f"{row['delta']:+.0%} | {row['p_value']:.3f} |")
        lines += ["", f"One-sided Fisher exact test, alpha {comparison['alpha']}, "
                      f"ignoring drops under {comparison['max_drop']:.0%}."]
    if report_url:
        lines += ["", f"[Full report]({report_url})"]
    return "\n".join(lines) + "\n"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
