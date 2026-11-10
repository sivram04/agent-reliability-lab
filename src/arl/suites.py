"""Resolve --suite values: paths, or built-in packs shipped inside the package.

    --suite scenarios/my_suite              a file or directory of scenario YAML
    --suite builtin:safety                  a built-in pack
    --suite builtin:safety,arl/scenarios    several, comma-separated
"""

from __future__ import annotations

from pathlib import Path

from .models import Scenario, Target

_SAFETY = ["library/adversarial_user", "library/prompt_injection", "library/privacy"]
BUILTIN = {
    "quick": ["quick"],                # 16 generic attacks, deterministic, seconds: the default for `arl check`
    "smoke": ["smoke"],                # 4 OrderBot sanity checks (the fixture agents)
    "rag": ["rag"],                    # injections and failures in retrieved documents (needs tools.retrieval)
    "tools": ["tools"],                # unauthorised actions and tool loops (needs tools.actions)
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


def load(spec: str | None, target: Target | None = None) -> list[Scenario]:
    """Load scenarios; with a target, bind placeholders and drop the ones that can't apply."""
    if not spec:
        return []
    scenarios = [s for p in resolve(spec) for s in Scenario.load_dir(p)]
    seen: set[str] = set()
    dupes = {s.id for s in scenarios if s.id in seen or seen.add(s.id)}
    if dupes:
        raise ValueError(f"duplicate scenario ids: {', '.join(sorted(dupes))}")
    return bind(scenarios, target)[0] if target else scenarios


# Adapters that run the agent in this process, where @arl.tool calls are visible and faults apply.
IN_PROCESS = {"python", "langgraph", "openai_agents", "pydantic_ai", "langchain", "crewai", "llamaindex"}


def _uses_tools(s: Scenario) -> bool:
    c = s.criteria
    return bool(s.faults or c.expect_tools or c.forbid_tools or c.max_tool_calls is not None)


def bind(scenarios: list[Scenario], target: Target) -> tuple[list[Scenario], list[tuple[str, str]]]:
    """Resolve $retrieval, $actions and $probe_question from the target. Returns (runnable, skipped),
    where skipped lists (scenario id, reason). A scenario is never run with an unresolved placeholder,
    and tool-dependent scenarios are skipped for black-box agents, where they would pass vacuously."""
    roles = target.tools
    kept, skipped = [], []
    for s in scenarios:
        text = s.model_dump_json()
        missing = []
        if "$retrieval" in text and not roles.get("retrieval"):
            missing.append("tools.retrieval")
        if "$actions" in text and not roles.get("actions"):
            missing.append("tools.actions")
        if "$probe_question" in text and not target.probe_question:
            missing.append("probe_question")
        if missing:
            skipped.append((s.id, f"set {', '.join(missing)} in the target"))
            continue
        if _uses_tools(s) and target.adapter not in IN_PROCESS:
            skipped.append((s.id, f"needs tool visibility; the {target.adapter} adapter is a black box"))
            continue
        if "$" not in text:
            kept.append(s)
            continue
        data = s.model_dump()
        data["turns"] = [t.replace("$probe_question", target.probe_question or "") for t in data["turns"]]
        for f in data["faults"]:
            if f["tool"] == "$retrieval":
                f["tool"] = roles["retrieval"][0]
        for key in ("forbid_tools", "expect_tools"):
            names = data["criteria"][key]
            data["criteria"][key] = [t for n in names for t in
                                     (roles.get("actions", []) if n == "$actions" else
                                      roles.get("retrieval", [])[:1] if n == "$retrieval" else [n])]
        kept.append(Scenario.model_validate(data))
    return kept, skipped
