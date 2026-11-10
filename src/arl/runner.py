"""Orchestrator: runs scenarios x repeats with bounded concurrency."""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field

from .adapters import Agent
from .cassette import call_context
from .faults import ToolBox, current_toolbox
from .judges import FACTUAL_RUBRICS, judge
from .llm import LLM
from .models import RunResult, Scenario
from .scoring import score
from .stats import wilson_ci
from .simuser import SimulatedUser
from .tracing import Trace

SAFETY_CATEGORIES = {"adversarial_user", "prompt_injection", "privacy"}


@dataclass
class RunConfig:
    repeats: int = 1
    seed: int = 0
    concurrency: int = 4
    user_llm: LLM | None = None  # enables simulated users for scenarios with a user_goal
    judge_llm: LLM | None = None  # enables rubric judges after deterministic checks pass
    secrets: list[str] = field(default_factory=list)


async def run_one(
    agent: Agent, scenario: Scenario, repeat: int, seed: int, cfg: RunConfig | None = None
) -> RunResult:
    cfg = cfg or RunConfig()
    random.seed(seed)
    transcript: list[dict] = []
    trace = Trace()
    error = None
    stop_reason = "script_end"
    box = ToolBox(scenario.faults, random.Random(f"{seed}:{scenario.id}"))
    current_toolbox.set(box)
    sim = SimulatedUser(cfg.user_llm, scenario) if cfg.user_llm and scenario.user_goal else None
    start = time.perf_counter()
    try:
        with trace.span("scenario", scenario_id=scenario.id, repeat=repeat, seed=seed):
            for turn in range(scenario.criteria.max_turns):
                call_context.set((scenario.id, repeat, turn))
                if turn < len(scenario.turns):
                    user_msg = scenario.turns[turn]
                elif sim:
                    with trace.span("user.turn", turn=turn):
                        user_msg, reason = await sim.next_message(transcript)
                    if user_msg is None:
                        stop_reason = reason
                        break
                else:
                    break
                transcript.append({"role": "user", "content": user_msg})
                box.turn = turn
                with trace.span("agent.turn", turn=turn) as span:
                    reply = await agent(list(transcript))
                    span["attrs"]["reply_chars"] = len(reply)
                transcript.append({"role": "assistant", "content": reply})
            else:
                stop_reason = "max_turns"
    except Exception as exc:  # agent crashes count as failures, not lab crashes
        error = f"{type(exc).__name__}: {exc}"
        stop_reason = "error"
    latency = time.perf_counter() - start
    result = RunResult(
        scenario_id=scenario.id,
        category=scenario.category,
        repeat=repeat,
        seed=seed,
        transcript=transcript,
        checks=score(scenario, transcript, latency, cfg.secrets, stop_reason, box.calls),
        latency_s=latency,
        error=error,
        stop_reason=stop_reason,
        spans=trace.spans,
        tool_calls=box.calls,
        faults_fired=box.faults_fired,
    )
    if cfg.judge_llm and result.passed:
        try:
            with trace.span("judge", scenario_id=scenario.id):
                result.checks += await judge(cfg.judge_llm, scenario, result)
        except Exception:
            # A judge outage (e.g. rate limits) leaves this run unjudged instead of aborting the
            # suite; the error is on the "judge" span, and unjudged runs are not exported for labels.
            pass
        result.spans = list(trace.spans)  # include the judge span
    return result


async def run_suite(
    agent: Agent, scenarios: list[Scenario], repeats: int = 1, seed: int = 0, concurrency: int = 4,
    cfg: RunConfig | None = None,
) -> list[RunResult]:
    cfg = cfg or RunConfig(repeats=repeats, seed=seed, concurrency=concurrency)
    sem = asyncio.Semaphore(cfg.concurrency)

    async def guarded(s: Scenario, r: int) -> RunResult:
        async with sem:
            return await run_one(agent, s, r, cfg.seed + r, cfg)

    return list(await asyncio.gather(*(guarded(s, r) for s in scenarios for r in range(cfg.repeats))))


def summarize(results: list[RunResult]) -> dict:
    total = len(results)
    passed = sum(r.passed for r in results)
    by_cat: dict[str, list[bool]] = {}
    for r in results:
        by_cat.setdefault(r.category, []).append(r.passed)
    faulted = [r for r in results if r.faults_fired]
    loops = [r for r in results if any(c.name == "max_tool_calls" and not c.passed for c in r.checks)]
    latencies = sorted(r.latency_s for r in results)
    safety = [r for r in results if r.category in SAFETY_CATEGORIES]
    injection = [r for r in results if r.category == "prompt_injection"]
    factual = [c for r in results for c in r.checks if c.name.removeprefix("judge:") in FACTUAL_RUBRICS]
    return {
        "runs": total,
        "passed": passed,
        "pass_rate": passed / total if total else 1.0,
        "pass_rate_ci95": wilson_ci(passed, total),
        "by_category": {k: sum(v) / len(v) for k, v in sorted(by_cat.items())},
        # F7 metrics
        "recovery_rate": sum(r.passed for r in faulted) / len(faulted) if faulted else None,
        "loop_rate": len(loops) / total if total else 0.0,
        "crash_rate": sum(r.error is not None for r in results) / total if total else 0.0,
        "tool_calls_per_run": sum(len(r.tool_calls) for r in results) / total if total else 0.0,
        "safety_violation_rate": sum(not r.passed for r in safety) / len(safety) if safety else None,
        "injection_resistance": sum(r.passed for r in injection) / len(injection) if injection else None,
        "hallucination_rate": sum(not c.passed for c in factual) / len(factual) if factual else None,
        "p95_latency_s": latencies[min(len(latencies) - 1, int(0.95 * len(latencies)))] if latencies else 0.0,
    }


def fingerprint(results: list[RunResult]) -> list[tuple]:
    """Timing-free view of results, for checking that a replay matches its recording."""
    return sorted(
        (r.scenario_id, r.repeat, r.seed, r.error, r.stop_reason, tuple(map(str, r.transcript)),
         tuple(str({k: v for k, v in t.items() if k != "latency_s"}) for t in r.tool_calls),
         tuple((c.name, c.passed) for c in r.checks if c.name != "latency"))
        for r in results
    )
