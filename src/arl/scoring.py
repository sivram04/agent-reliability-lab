"""Deterministic checks (F6, first stage). LLM judges come in Phase 4."""

from __future__ import annotations

from .models import Check, Scenario


def score(scenario: Scenario, transcript: list[dict], latency_s: float) -> list[Check]:
    replies = " ".join(m["content"] for m in transcript if m["role"] == "assistant").lower()
    c = scenario.criteria
    checks = [Check(name=f"contains:{s}", passed=s.lower() in replies) for s in c.must_contain]
    checks += [
        Check(name=f"forbidden:{s}", passed=s.lower() not in replies) for s in c.must_not_contain
    ]
    if c.max_latency_s is not None:
        checks.append(
            Check(
                name="latency",
                passed=latency_s <= c.max_latency_s,
                detail=f"{latency_s:.3f}s <= {c.max_latency_s}s",
            )
        )
    return checks
