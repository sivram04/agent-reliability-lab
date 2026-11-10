"""Re-judge labelled conversations with the current rubrics, without re-running the agent.

    python scripts/rejudge.py labels/batch1_claude.jsonl --judge-llm gemini:gemini-3.5-flash-lite --out labels/out.jsonl

Writes the same items with `judge` and `judge_reasons` replaced, so `arl label agreement` on the output
measures the current judge against the existing labels.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from arl import suites  # noqa: E402
from arl.judges import judge  # noqa: E402
from arl.llm import build_llm  # noqa: E402
from arl.models import RunResult  # noqa: E402


async def main(path: Path, spec: str, out: Path) -> None:
    llm = build_llm(spec, temperature=0.0, role="judge")
    by_id = {s.id: s for s in suites.load("builtin:library")}
    items = [json.loads(line) for line in path.open(encoding="utf-8")]
    for n, item in enumerate(items, 1):
        scenario = by_id[item["scenario_id"]]
        result = RunResult(scenario_id=scenario.id, category=scenario.category, repeat=item["repeat"], seed=0,
                           transcript=item["transcript"], checks=[], latency_s=0.0,
                           tool_calls=item.get("tool_calls", []))
        checks = await judge(llm, scenario, result)
        item["judge"] = all(c.passed for c in checks)
        item["judge_reasons"] = {c.name: c.detail for c in checks}
        print(f"[{n}/{len(items)}] {scenario.id}: {'pass' if item['judge'] else 'FAIL'}", flush=True)
    with out.open("w", encoding="utf-8", newline="\n") as f:
        for item in items:
            f.write(json.dumps(item) + "\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("labels", type=Path)
    ap.add_argument("--judge-llm", required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    asyncio.run(main(a.labels, a.judge_llm, a.out))
