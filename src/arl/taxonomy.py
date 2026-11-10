"""What each scenario covers: the agent capability it exercises and the OWASP risks it tests.

Any agent, whatever it is called, is a combination of capabilities. Covering every capability
covers every kind of agent built from them. Scenarios carry explicit tags (`cap:memory`,
`owasp:LLM01`, `agentic:T1`); older scenarios without tags are classified from their category
and tags, so reports can always show coverage.
"""

from __future__ import annotations

from .models import Scenario

CAPABILITIES = {
    "conversation": "Talks to users: chat and support bots, assistants",
    "rag": "Answers from retrieved documents or search",
    "tools": "Calls tools and APIs that change things",
    "memory": "Remembers across turns or sessions",
    "multiagent": "Delegates to or receives messages from other agents",
    "code": "Writes and runs code",
    "browsing": "Reads web pages or drives a browser",
    "multimodal": "Reads documents, images or other non-chat input",
}

# OWASP Top 10 for LLM Applications, 2025.
OWASP_LLM = {
    "LLM01": "Prompt Injection",
    "LLM02": "Sensitive Information Disclosure",
    "LLM03": "Supply Chain",
    "LLM04": "Data and Model Poisoning",
    "LLM05": "Improper Output Handling",
    "LLM06": "Excessive Agency",
    "LLM07": "System Prompt Leakage",
    "LLM08": "Vector and Embedding Weaknesses",
    "LLM09": "Misinformation",
    "LLM10": "Unbounded Consumption",
}

# OWASP Agentic AI threats (Agentic Security Initiative).
AGENTIC = {
    "T1": "Memory Poisoning",
    "T2": "Tool Misuse",
    "T3": "Privilege Compromise",
    "T4": "Resource Overload",
    "T5": "Cascading Hallucination",
    "T6": "Intent Breaking and Goal Manipulation",
    "T7": "Misaligned and Deceptive Behaviors",
    "T8": "Repudiation and Untraceability",
    "T9": "Identity Spoofing and Impersonation",
    "T10": "Overwhelming Human in the Loop",
    "T11": "Unexpected RCE and Code Attacks",
    "T12": "Agent Communication Poisoning",
    "T13": "Rogue Agents in Multi-Agent Systems",
    "T14": "Human Attacks on Multi-Agent Systems",
    "T15": "Human Manipulation",
}

# Not testable by running conversations against an agent; reported as out of scope, not as gaps.
OUT_OF_SCOPE = {"LLM03": "supply chain is a dependency and model-provenance review",
                "T8": "repudiation needs audit-log review, not conversation tests"}


def classify(s: Scenario) -> dict[str, list[str]]:
    """{"capability": [...], "owasp": [...], "agentic": [...]} from explicit tags, else inferred."""
    tags = set(s.tags)
    caps = sorted(t.split(":", 1)[1] for t in tags if t.startswith("cap:"))
    owasp = sorted(t.split(":", 1)[1] for t in tags if t.startswith("owasp:"))
    agentic = sorted(t.split(":", 1)[1] for t in tags if t.startswith("agentic:"))
    if caps or owasp or agentic:
        return {"capability": caps, "owasp": owasp, "agentic": agentic}

    inferred: dict[str, set[str]] = {"capability": set(), "owasp": set(), "agentic": set()}
    text = f"{s.id} {' '.join(tags)}".lower()
    c = s.category
    indirect = "indirect" in text or "tool-output" in text or "rag" in text
    inferred["capability"].add("rag" if indirect or c == "knowledge_conflict" else
                               "tools" if c in ("tool_chaos", "cost_loop") or "tools" in tags else "conversation")
    if c == "prompt_injection":
        inferred["owasp"] |= {"LLM01", "LLM07"}
        inferred["agentic"].add("T6")
    if c == "adversarial_user":
        inferred["owasp"] |= {"LLM01", "LLM07"}
        inferred["agentic"] |= {"T6", "T15"}
        if "excessive-agency" in tags:
            inferred["owasp"].add("LLM06")
            inferred["agentic"] |= {"T2", "T3"}
    if c == "privacy":
        inferred["owasp"].add("LLM02")
        inferred["agentic"].add("T9" if any(w in text for w in ("spouse", "employee", "developer")) else "T15")
    if c == "knowledge_conflict" or "poison" in text:
        inferred["owasp"] |= {"LLM04", "LLM09"}
        inferred["agentic"].add("T5")
    if c == "tool_chaos":
        inferred["agentic"].add("T2")
        if s.criteria.max_tool_calls is not None:
            inferred["owasp"].add("LLM10")
    if c == "cost_loop":
        inferred["owasp"].add("LLM10")
        inferred["agentic"].add("T4")
    if indirect:
        inferred["owasp"] |= {"LLM01", "LLM08"} if "rag" in text else {"LLM01"}
    return {k: sorted(v) for k, v in inferred.items()}


def coverage(scenarios: list[Scenario]) -> dict:
    """Which capabilities and OWASP risks a set of scenarios covers, with counts."""
    counts: dict[str, dict[str, int]] = {"capability": {}, "owasp": {}, "agentic": {}}
    for s in scenarios:
        for kind, ids in classify(s).items():
            for i in ids:
                counts[kind][i] = counts[kind].get(i, 0) + 1
    universe = {"capability": CAPABILITIES, "owasp": OWASP_LLM, "agentic": AGENTIC}
    return {kind: {"covered": dict(sorted(counts[kind].items())),
                   "missing": [k for k in universe[kind] if k not in counts[kind] and k not in OUT_OF_SCOPE],
                   "out_of_scope": {k: v for k, v in OUT_OF_SCOPE.items() if k in universe[kind]}}
            for kind in universe}
