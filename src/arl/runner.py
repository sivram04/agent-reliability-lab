"""Orchestrator: runs scenarios x repeats with bounded concurrency."""

from __future__ import annotations

import asyncio
import random
import time

from .adapters import Agent
from .cassette import call_context
from .models import RunResult, Scenario
from .scoring import score
from .tracing import Trace


async def run_one(agent: Agent, scenario: Scenario, repeat: int, seed: int) -> RunResult:
    random.seed(seed)
    transcript: list[dict] = []
    trace = Trace()
    error = None
    start = time.perf_counter()
    try:
        with trace.span("scenario", scenario_id=scenario.id, repeat=repeat, seed=seed):
            for turn, user_msg in enumerate(scenario.turns[: scenario.criteria.max_turns]):
                transcript.append({"role": "user", "content": user_msg})
                call_context.set((scenario.id, repeat, turn))
                with trace.span("agent.turn", turn=turn) as span:
                    reply = await agent(list(transcript))
                    span["attrs"]["reply_chars"] = len(reply)
                transcript.append({"role": "assistant", "content": reply})
    except Exception as exc:  # agent crashes count as failures, not lab crashes
        error = f"{type(exc).__name__}: {exc}"
    latency = time.perf_counter() - start
    return RunResult(
        scenario_id=scenario.id,
        category=scenario.category,
        repeat=repeat,
        seed=seed,
        transcript=transcript,
        checks=score(scenario, transcript, latency),
        latency_s=latency,
        error=error,
        spans=trace.spans,
    )


async def run_suite(
    agent: Agent, scenarios: list[Scenario], repeats: int = 1, seed: int = 0, concurrency: int = 4
) -> list[RunResult]:
    sem = asyncio.Semaphore(concurrency)

    async def guarded(s: Scenario, r: int) -> RunResult:
        async with sem:
            return await run_one(agent, s, r, seed + r)

    return list(await asyncio.gather(*(guarded(s, r) for s in scenarios for r in range(repeats))))


def summarize(results: list[RunResult]) -> dict:
    total = len(results)
    passed = sum(r.passed for r in results)
    by_cat: dict[str, list[bool]] = {}
    for r in results:
        by_cat.setdefault(r.category, []).append(r.passed)
    return {
        "runs": total,
        "passed": passed,
        "pass_rate": passed / total if total else 1.0,
        "by_category": {k: sum(v) / len(v) for k, v in sorted(by_cat.items())},
    }


def fingerprint(results: list[RunResult]) -> list[tuple]:
    """Timing-free view of results, for checking that a replay matches its recording."""
    return sorted(
        (r.scenario_id, r.repeat, r.seed, r.error, tuple(map(str, r.transcript)),
         tuple((c.name, c.passed) for c in r.checks if c.name != "latency"))
        for r in results
    )
