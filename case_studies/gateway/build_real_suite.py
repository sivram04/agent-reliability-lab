"""Real-model suite (sized for a free Gemini quota): every seed attack, a seeded sample of
obfuscated variants and of the red-team bypasses found against the gateway, and the benign set."""

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from arl.models import Criteria, Scenario  # noqa: E402

HERE = Path(__file__).parent
OUT = HERE / "suite_real"
rng = random.Random(0)

attacks = Scenario.load_dir(HERE / "suite" / "attacks")
seeds = [s for s in attacks if not s.id.startswith("gen-")]
variants = rng.sample([s for s in attacks if s.id.startswith("gen-")], 25)
bypasses = rng.sample(Scenario.load_dir(ROOT / "docs" / "results" / "gateway" / "redteam"), 25)
bypasses = [s.model_copy(update={"criteria": Criteria(forbid_secrets=True)}) for s in bypasses]
benign = Scenario.load_dir(HERE / "suite" / "benign")

for sub, items in (("attacks", seeds + variants + bypasses), ("benign", benign)):
    folder = OUT / sub
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.yaml"):
        old.unlink()
    for s in items:
        (folder / f"{s.id}.yaml").write_text(s.to_yaml(), encoding="utf-8", newline="\n")
    print(sub, len(items))
