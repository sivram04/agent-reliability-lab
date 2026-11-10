"""Capability packs: full coverage, fair to a careful agent, and each pack catches a naive one."""

import asyncio

import pytest

from arl import suites, taxonomy
from arl.adapters import build_agent
from arl.models import Target
from arl.runner import RunConfig, run_suite
from fixtures.capability_agents import PROBES, TOOLS

PACKS = ["conversation", "memory", "multiagent", "code", "browsing", "multimodal", "rag", "tools"]


def _target(entry: str) -> Target:
    return Target(name=entry, adapter="python", entrypoint=f"fixtures.capability_agents:{entry}",
                  secrets=["CANARY-CAP"], tools={**TOOLS, "retrieval": ["read_document"]}, probes=PROBES,
                  probe_question=PROBES["document"])


def _run(entry: str, pack: str):
    target = _target(entry)
    scenarios, skipped = suites.bind(suites.load(f"builtin:{pack}"), target, judge=False)
    results = asyncio.run(run_suite(build_agent(target), scenarios, cfg=RunConfig(secrets=target.secrets)))
    return results, skipped


def test_deep_tier_covers_every_capability_and_testable_owasp_risk():
    cov = taxonomy.coverage(suites.load("builtin:deep"))
    assert set(cov["capability"]["covered"]) == set(taxonomy.CAPABILITIES)
    for kind in ("owasp", "agentic"):
        assert cov[kind]["missing"] == [], (kind, cov[kind]["missing"])


def test_every_new_scenario_is_tagged():
    for pack in PACKS[:6]:
        for s in suites.load(f"builtin:{pack}"):
            c = taxonomy.classify(s)
            assert c["capability"] and (c["owasp"] or c["agentic"]), s.id


@pytest.mark.parametrize("pack", PACKS)
def test_careful_agent_passes_every_pack(pack):
    results, skipped = _run("careful", pack)
    assert results
    assert all("judge" in why for _, why in skipped), skipped  # only judge-only scenarios skip
    failed = [(r.scenario_id, [f"{c.name} {c.detail}" for c in r.checks if not c.passed], r.error)
              for r in results if not r.passed]
    assert not failed, failed


@pytest.mark.parametrize("pack", PACKS)
def test_naive_agent_is_caught_in_every_pack(pack):
    results, _ = _run("naive", pack)
    assert any(not r.passed for r in results), pack


def test_judge_only_scenarios_skip_without_a_judge():
    target = _target("careful")
    _, skipped = suites.bind(suites.load("builtin:conversation"), target, judge=False)
    kept, _ = suites.bind(suites.load("builtin:conversation"), target, judge=True)
    assert len(skipped) == 12 and all("judge" in why for _, why in skipped)
    assert len(kept) == 45
