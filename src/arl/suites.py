"""Resolve --suite values: paths, or built-in packs shipped inside the package.

    --suite scenarios/my_suite              a file or directory of scenario YAML
    --suite builtin:safety                  a built-in pack
    --suite builtin:safety,arl/scenarios    several, comma-separated
"""

from __future__ import annotations

import re
from pathlib import Path

from .models import Scenario, Target

_SAFETY = ["library/adversarial_user", "library/prompt_injection", "library/privacy"]
_CAPABILITY = ["rag", "tools", "conversation", "memory", "multiagent", "code", "browsing", "multimodal"]
BUILTIN = {
    # Tiers: pick by how much time you have. Scenarios that don't apply to a target are skipped.
    "quick": ["quick"],                # seconds: 16 generic attacks, deterministic; the default for `arl check`
    "standard": [*_SAFETY, *_CAPABILITY],    # minutes: before merging
    "deep": ["library", *_CAPABILITY],       # everything; add --judge-llm and --repeats 3 before a release
    "smoke": ["smoke"],                # 4 OrderBot sanity checks (the fixture agents)
    "rag": ["rag"],                    # injections and failures in retrieved documents (needs tools.retrieval)
    "tools": ["tools"],                # unauthorised actions and tool loops (needs tools.actions)
    "conversation": ["conversation"],  # leaks in many languages/formats, spoofing, crescendo, output handling
    "memory": ["memory"],              # memory poisoning (needs tools.memory for the tool-based ones)
    "multiagent": ["multiagent"],      # poisoned agent-to-agent messages, relays, loops (needs tools.delegate)
    "code": ["code"],                  # unsafe code execution (needs tools.code)
    "browsing": ["browsing"],          # injections in web pages, SSRF (needs tools.browser)
    "multimodal": ["multimodal"],      # instructions hidden in documents and images (needs tools.document)
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
    return bool(s.faults or c.expect_tools or c.forbid_tools or c.forbid_tool_args or c.max_tool_calls is not None)


TOOL_FIELDS = ("forbid_tools", "expect_tools")
ROLE = re.compile(r"^\$(\w+)$")
PROBE = re.compile(r"\$probe(?::(\w+)|_question)")


def _other_checks(s: Scenario) -> bool:
    """Whether the scenario checks anything besides forbidden tools."""
    c = s.criteria
    return bool(c.must_contain or c.must_not_contain or c.forbid_secrets or c.expect_tools or c.forbid_patterns
                or c.forbid_tool_args or c.max_tool_calls is not None or c.max_reply_chars is not None
                or c.max_latency_s is not None or c.rubrics or c.extra)


def _roles_used(s: Scenario) -> set[str]:
    names = [f.tool for f in s.faults] + list(s.criteria.expect_tools) + list(s.criteria.forbid_tools)
    return {m.group(1) for n in names if (m := ROLE.match(n))}


def _probes_used(s: Scenario) -> set[str]:
    return {m.group(1) or "" for t in s.turns for m in PROBE.finditer(t)}


def _probe(target: Target, role: str) -> str | None:
    return target.probes.get(role) or target.probe_question if role else target.probe_question


def bind(scenarios: list[Scenario], target: Target,
         judge: bool = True) -> tuple[list[Scenario], list[tuple[str, str]]]:
    """Resolve tool-role placeholders from the target and drop scenarios that can't apply.

    `$role` (e.g. $retrieval, $actions, $memory, $code, $browser, $delegate, $document) names the target's
    `tools[role]`: the first tool in faults and expect_tools, every tool in forbid_tools. In turns,
    `$probe_question` and `$probe:role` become `probe_question` / `probes[role]`. Returns (runnable,
    skipped) with a reason per skipped scenario: missing roles, tools the target doesn't declare, or
    tool-dependent scenarios on black-box agents, where they would pass vacuously. With judge=False,
    judge-only scenarios are skipped too: without a judge they would pass without testing anything."""
    roles = target.tools
    declared = {t for names in roles.values() for t in names}
    kept, skipped = [], []
    for s in scenarios:
        if not judge and not _other_checks(s) and not s.criteria.forbid_tools and not s.user_goal:
            # Nothing deterministic to check: without a judge it would pass for free.
            skipped.append((s.id, "has no checks; add criteria or --judge-llm"))
            continue
        if s.criteria.judge_only and not judge:
            skipped.append((s.id, "only an LLM judge can grade it; add --judge-llm"))
            continue
        if _uses_tools(s) and target.adapter not in IN_PROCESS:
            skipped.append((s.id, f"needs tool visibility; the {target.adapter} adapter is a black box"))
            continue
        # A role used only to forbid tools is vacuous when the agent has no such tools: drop that check
        # instead of skipping the scenario. Roles the scenario actually exercises must be declared.
        needed = {m.group(1) for n in [f.tool for f in s.faults] + list(s.criteria.expect_tools)
                  if (m := ROLE.match(n))}
        missing = [f"tools.{r}" for r in sorted(needed) if not roles.get(r)]
        forbid_only = {m.group(1) for n in s.criteria.forbid_tools if (m := ROLE.match(n))} - needed
        if any(not roles.get(r) for r in forbid_only) and not _other_checks(s):
            # Dropping the forbid check would leave nothing to test: skip rather than pass vacuously.
            missing += [f"tools.{r}" for r in sorted(forbid_only) if not roles.get(r)]
        if "$probe_expect" in s.criteria.must_contain and not target.probe_expect and "control" in s.tags:
            missing.append("probe_expect")  # a control scenario is meaningless without the expected answer
        missing += sorted({f"probes.{r}" if r else "probe_question" for r in _probes_used(s) if not _probe(target, r)})
        if missing:
            skipped.append((s.id, f"set {', '.join(missing)} in the target"))
            continue
        named = {f.tool for f in s.faults} | set(s.criteria.expect_tools) | set(s.criteria.forbid_tools)
        undeclared = sorted(t for t in named if t != "*" and not t.startswith("$") and t not in declared)
        if undeclared:
            # Written for a specific agent's tools: on any other agent it would fail or pass for no reason.
            skipped.append((s.id, f"uses tools your target doesn't declare ({', '.join(undeclared)})"))
            continue
        if _uses_tools(s) and target.adapter not in IN_PROCESS:
            skipped.append((s.id, f"needs tool visibility; the {target.adapter} adapter is a black box"))
            continue
        if not _roles_used(s) and not _probes_used(s) and "$probe_expect" not in s.criteria.must_contain:
            kept.append(s)
            continue
        data = s.model_dump()
        data["turns"] = [PROBE.sub(lambda m: _probe(target, m.group(1) or "") or "", t) for t in data["turns"]]
        for f in data["faults"]:
            if m := ROLE.match(f["tool"]):
                f["tool"] = roles[m.group(1)][0]
        for key in TOOL_FIELDS:
            out = []
            for n in data["criteria"][key]:
                m = ROLE.match(n)
                out += (roles.get(m.group(1), []) if key == "forbid_tools" else roles[m.group(1)][:1]) if m else [n]
            data["criteria"][key] = out
        data["criteria"]["must_contain"] = [target.probe_expect if c == "$probe_expect" else c
                                            for c in data["criteria"]["must_contain"]
                                            if c != "$probe_expect" or target.probe_expect]
        kept.append(Scenario.model_validate(data))
    return kept, skipped
