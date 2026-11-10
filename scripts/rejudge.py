"""Re-judge labelled conversations with the current rubrics, without re-running the agent.

    python scripts/rejudge.py labels/batch1_ai_labelled.jsonl --judge-llm gemini:gemini-3.5-flash-lite --out labels/out.jsonl

Writes the same items with `judge` and `judge_reasons` replaced, so `arl label agreement` on the output
measures the current judge against the existing labels. Progress is saved after every item: re-running
the same command resumes where it stopped.
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from arl import suites  # noqa: E402
from arl.judges import judge  # noqa: E402
from arl.llm import build_llm  # noqa: E402
from arl.models import RunResult  # noqa: E402


def _key(item: dict) -> str:
    return f"{item.get('run_id')}|{item['scenario_id']}|{item['repeat']}"


async def main(path: Path, spec: str, out: Path, per_item_timeout: float) -> None:
    llm = build_llm(spec, temperature=0.0, role="judge")
    by_id = {s.id: s for s in suites.load("builtin:library")}
    items = [json.loads(line) for line in path.open(encoding="utf-8")]
    done = {}
    if out.exists():
        done = {_key(i): i for i in (json.loads(line) for line in out.open(encoding="utf-8"))}
    todo = [i for i in items if _key(i) not in done]
    print(f"{len(done)} already judged, {len(todo)} to go", flush=True)
    with out.open("a", encoding="utf-8", newline="\n") as f:
        for n, item in enumerate(todo, 1):
            scenario = by_id[item["scenario_id"]]
            result = RunResult(scenario_id=scenario.id, category=scenario.category, repeat=item["repeat"], seed=0,
                               transcript=item["transcript"], checks=[], latency_s=0.0,
                               tool_calls=item.get("tool_calls", []))
            t0 = time.time()
            try:
                checks = await asyncio.wait_for(judge(llm, scenario, result), per_item_timeout)
            except Exception as exc:  # noqa: BLE001  report and move on; a re-run retries it
                print(f"[{n}/{len(todo)}] {scenario.id}: ERROR {type(exc).__name__}: {exc}", flush=True)
                continue
            item = {**item, "judge": all(c.passed for c in checks),
                    "judge_reasons": {c.name: c.detail for c in checks}}
            f.write(json.dumps(item) + "\n")
            f.flush()
            print(f"[{n}/{len(todo)}] {scenario.id}: {'pass' if item['judge'] else 'FAIL'} ({time.time() - t0:.1f}s)",
                  flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("labels", type=Path)
    ap.add_argument("--judge-llm", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--per-item-timeout", type=float, default=180.0)
    a = ap.parse_args()
    asyncio.run(main(a.labels, a.judge_llm, a.out, a.per_item_timeout))
