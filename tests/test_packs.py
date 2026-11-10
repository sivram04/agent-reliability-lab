"""builtin:rag and builtin:tools: placeholder binding, skipping, and catching a naive RAG agent."""

import asyncio

from arl import suites
from arl.adapters import build_agent
from arl.models import Target
from arl.runner import RunConfig, run_suite

ROLES = {"retrieval": ["search_docs"], "actions": ["send_email"]}


def _target(entry: str, **kw) -> Target:
    return Target(name=entry, adapter="python", entrypoint=f"fixtures.rag_agents:{entry}",
                  secrets=["CANARY-RAG"], tools=ROLES, probe_question="What is the refund policy?", **kw)


def _run(target: Target):
    scenarios, skipped = suites.bind(suites.load("builtin:rag,builtin:tools"), target)
    results = asyncio.run(run_suite(build_agent(target), scenarios, cfg=RunConfig(secrets=target.secrets)))
    return results, skipped


def test_placeholders_are_bound():
    scenarios, skipped = suites.bind(suites.load("builtin:rag,builtin:tools"), _target("careful"))
    assert not skipped and len(scenarios) == 21
    text = "".join(s.model_dump_json() for s in scenarios)
    assert not any(p in text for p in ("$retrieval", "$actions", "$probe_question"))
    assert "search_docs" in text and "What is the refund policy?" in text


def test_careful_agent_passes_everything():
    results, _ = _run(_target("careful"))
    failed = [(r.scenario_id, [c.name for c in r.checks if not c.passed], r.error) for r in results if not r.passed]
    assert not failed, failed


def test_naive_agent_is_caught_where_expected():
    results, _ = _run(_target("naive"))
    failing = {r.scenario_id for r in results if not r.passed}
    assert {"rag-inject-override-secret", "rag-inject-trigger-action", "rag-chaos-error-once",
            "tools-unauthorised-mass-email"} <= failing
    leak = next(r for r in results if r.scenario_id == "rag-inject-override-secret")
    assert any(c.name == "no_secret_leak" and not c.passed for c in leak.checks)


def test_missing_roles_and_black_boxes_are_skipped_not_passed():
    bare = Target(name="b", adapter="python", entrypoint="fixtures.rag_agents:careful")
    kept, skipped = suites.bind(suites.load("builtin:rag,builtin:tools"), bare)
    assert not kept and len(skipped) == 21 and any("tools.retrieval" in why for _, why in skipped)

    http = Target(name="h", adapter="http", url="http://localhost:1/x", tools=ROLES, probe_question="q?")
    kept, skipped = suites.bind(suites.load("builtin:rag,builtin:tools,builtin:quick"), http)
    assert {s.category for s in kept} <= {"prompt_injection", "adversarial_user", "privacy"}
    assert all("black box" in why for _, why in skipped) and len(skipped) == 21
