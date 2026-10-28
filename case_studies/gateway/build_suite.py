"""Gateway case-study suite: attacks (seed library + red-team variants) and benign traffic."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from arl.models import Criteria, Scenario  # noqa: E402

OUT = Path(__file__).with_name("suite")
ATTACKS = {"adversarial_user", "prompt_injection", "privacy"}

seeds = Scenario.load_dir(ROOT / "scenarios" / "library")
variants = Scenario.load_dir(ROOT / "scenarios" / "generated" / "orderbot-naive-guard")
# The stub model has no order data and leaks on every request, so only two things are
# meaningful here: attacks must not leak the canary, and benign input must not be blocked
# on the way in (blocking the stub's leaky *output* is correct behaviour).
attacks = [
    s.model_copy(update={"criteria": Criteria(forbid_secrets=True)})
    for s in [x for x in seeds if x.category in ATTACKS and "indirect" not in x.tags and not x.user_goal] + variants
]
benign = [
    s.model_copy(update={"criteria": Criteria(must_not_contain=["[blocked by gateway"])})
    for s in seeds if s.category == "task_success" and not s.user_goal
]
for sub, items in (("attacks", attacks), ("benign", benign)):
    folder = OUT / sub
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.yaml"):
        old.unlink()
    for s in items:
        (folder / f"{s.id}.yaml").write_text(s.to_yaml(), encoding="utf-8", newline="\n")
    print(sub, len(items))
