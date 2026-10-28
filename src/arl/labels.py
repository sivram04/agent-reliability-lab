"""Human labels and judge-human agreement (F6).

Workflow:
    arl label export --run RUN_ID --out labels/batch1.jsonl --sample 200
    arl label annotate labels/batch1.jsonl      # y / n / s(kip) / q(uit), resumable
    arl label agreement labels/batch1.jsonl    # agreement %, Cohen's kappa, confusion matrix

The judge's verdict for an item is "all judge:* checks passed". Items the judge
never saw (a deterministic check failed first) are excluded from the export.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from .stats import cohen_kappa
from .store import Store


def export(store: Store, run_id: str, out: Path, sample: int | None = None, seed: int = 0) -> int:
    items = []
    for r in store.load_results(run_id):
        judged = [c for c in r.checks if c.name.startswith("judge:")]
        if not judged:
            continue
        items.append({
            "run_id": run_id, "scenario_id": r.scenario_id, "repeat": r.repeat, "category": r.category,
            "transcript": r.transcript, "tool_calls": r.tool_calls,
            "judge": all(c.passed for c in judged),
            "judge_reasons": {c.name: c.detail for c in judged},
            "human": None,
        })
    if sample and len(items) > sample:
        items = random.Random(seed).sample(items, sample)
    write(out, items)
    return len(items)


def read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(i, default=str) + "\n" for i in items), encoding="utf-8")


def agreement(items: list[dict]) -> dict:
    labeled = [i for i in items if i.get("human") is not None]
    judge = [bool(i["judge"]) for i in labeled]
    human = [bool(i["human"]) for i in labeled]
    n = len(labeled)
    by_cat: dict[str, list[bool]] = {}
    for i in labeled:
        by_cat.setdefault(i["category"], []).append(bool(i["judge"]) == bool(i["human"]))
    return {
        "labeled": n,
        "unlabeled": len(items) - n,
        "agreement": sum(j == h for j, h in zip(judge, human)) / n if n else None,
        "cohen_kappa": cohen_kappa(judge, human) if n else None,
        "confusion": {
            "judge_pass_human_pass": sum(j and h for j, h in zip(judge, human)),
            "judge_pass_human_fail": sum(j and not h for j, h in zip(judge, human)),
            "judge_fail_human_pass": sum(not j and h for j, h in zip(judge, human)),
            "judge_fail_human_fail": sum(not j and not h for j, h in zip(judge, human)),
        },
        "agreement_by_category": {k: sum(v) / len(v) for k, v in sorted(by_cat.items())},
    }
