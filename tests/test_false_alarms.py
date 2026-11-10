"""False-alarm guard: built-in generic scenarios must pass against careful reference agents.

A failure here means a scenario would flag a well-behaved agent, so the scenario must be fixed.
"""

import asyncio

from arl import suites
from arl.adapters import build_agent
from arl.models import Target
from arl.runner import RunConfig, run_suite


def _failures(target: Target, spec: str):
    scenarios, skipped = suites.bind(suites.load(spec), target)
    results = asyncio.run(run_suite(build_agent(target), scenarios, cfg=RunConfig(secrets=target.secrets)))
    bad = [(r.scenario_id, [f"{c.name} {c.detail}" for c in r.checks if not c.passed], r.error)
           for r in results if not r.passed]
    return bad, len(scenarios), skipped


def test_generic_packs_do_not_flag_a_careful_agent():
    target = Target(name="ref", adapter="python", entrypoint="fixtures.reference_agent:respond",
                    secrets=["CANARY-REF"])
    bad, ran, skipped = _failures(target, "builtin:quick,builtin:safety")
    assert not bad, bad
    assert ran >= 70  # most of the safety library applies to any agent
    assert all("doesn't declare" in why for _, why in skipped)  # only agent-specific ones are skipped


def test_rag_and_tool_packs_do_not_flag_a_careful_rag_agent():
    target = Target(name="rag", adapter="python", entrypoint="fixtures.rag_agents:careful", secrets=["CANARY-RAG"],
                    tools={"retrieval": ["search_docs"], "actions": ["send_email"]},
                    probe_question="What is the refund policy?")
    bad, ran, skipped = _failures(target, "builtin:rag,builtin:tools")
    assert not bad, bad
    assert ran == 19 and not skipped
