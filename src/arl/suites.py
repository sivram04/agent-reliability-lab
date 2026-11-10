"""Resolve --suite values: paths, or built-in packs shipped inside the package.

    --suite scenarios/my_suite              a file or directory of scenario YAML
    --suite builtin:safety                  a built-in pack
    --suite builtin:safety,arl/scenarios    several, comma-separated
"""

from __future__ import annotations

from pathlib import Path

from .models import Scenario

_SAFETY = ["library/adversarial_user", "library/prompt_injection", "library/privacy"]
BUILTIN = {
    "smoke": ["smoke"],                # 4 quick checks, seconds to run
    "safety": _SAFETY,                 # jailbreaks, injections, secret/PII extraction: works on any agent
    "library": ["library"],            # everything, incl. OrderBot-style task and tool-chaos scenarios
    **{c: [f"library/{c}"] for c in ("adversarial_user", "prompt_injection", "privacy", "task_success",
                                     "tool_chaos", "knowledge_conflict", "cost_loop")},
}


def builtin_root() -> Path:
    """Installed wheels carry the packs at arl/scenarios; a source checkout has them at the repo root."""
    packaged = Path(__file__).parent / "scenarios"
    return packaged if packaged.is_dir() else Path(__file__).resolve().parents[2] / "scenarios"


def resolve(spec: str) -> list[Path]:
    paths: list[Path] = []
    for part in filter(None, (p.strip() for p in spec.split(","))):
        if part.startswith("builtin:"):
            name = part.removeprefix("builtin:")
            if name not in BUILTIN:
                raise ValueError(f"unknown built-in suite {name!r}; choose from {', '.join(sorted(BUILTIN))}")
            paths += [builtin_root() / rel for rel in BUILTIN[name]]
        else:
            path = Path(part)
            if not path.exists():
                raise ValueError(f"suite path {part!r} does not exist")
            paths.append(path)
    return paths


def load(spec: str | None) -> list[Scenario]:
    if not spec:
        return []
    scenarios = [s for p in resolve(spec) for s in Scenario.load_dir(p)]
    seen: set[str] = set()
    dupes = {s.id for s in scenarios if s.id in seen or seen.add(s.id)}
    if dupes:
        raise ValueError(f"duplicate scenario ids: {', '.join(sorted(dupes))}")
    return scenarios
