"""Phase 3: tool interception and fault injection."""

import asyncio
import random

import pytest

from arl import Fault, ToolError, tool
from arl.adapters import build_agent
from arl.cassette import Cassette
from arl.faults import RateLimitError, ToolBox, current_toolbox
from arl.models import Scenario, Target
from arl.runner import RunConfig, fingerprint, run_suite, summarize

TOOL_SUITE = [s for s in Scenario.load_dir("scenarios/library") if s.faults or s.criteria.max_tool_calls]


@tool
def lookup(key: str) -> dict:
    return {"key": key, "status": "ok", "count": 3}


def _with_box(*faults, seed=0):
    box = ToolBox(list(faults), random.Random(seed))
    token = current_toolbox.set(box)
    return box, token


def test_decorator_is_noop_outside_a_run():
    assert current_toolbox.get() is None
    assert lookup(key="a") == {"key": "a", "status": "ok", "count": 3}


@pytest.mark.parametrize("mode,exc", [("error", ToolError), ("timeout", TimeoutError), ("rate_limit", RateLimitError)])
def test_raising_faults(mode, exc):
    box, token = _with_box(Fault(mode=mode))
    with pytest.raises(exc):
        lookup(key="a")
    current_toolbox.reset(token)
    assert box.calls[0]["fault"] == mode and "error" in box.calls[0]


@pytest.mark.parametrize("mode,check", [
    ("bad_data", lambda r: r["status"] == "corrupted" and r["count"] == -4),
    ("partial", lambda r: list(r) == ["key"]),
    ("schema_drift", lambda r: "status_v2" in r and "status" not in r),
    ("inject", lambda r: r["note"] == "hi"),
    ("poison", lambda r: r["status"] == "fake"),
])
def test_data_faults(mode, check):
    _, token = _with_box(Fault(mode=mode, payload="hi", data={"status": "fake"}))
    result = lookup(key="a")
    current_toolbox.reset(token)
    assert check(result)


def test_first_n_makes_faults_transient():
    box, token = _with_box(Fault(tool="lookup", mode="error", first_n=2))
    outcomes = []
    for _ in range(3):
        try:
            outcomes.append(lookup(key="a")["status"])
        except ToolError:
            outcomes.append("err")
    current_toolbox.reset(token)
    assert outcomes == ["err", "err", "ok"] and box.faults_fired == 2


def test_rate_is_seeded():
    def pattern(seed):
        box, token = _with_box(Fault(mode="error", rate=0.5), seed=seed)
        for _ in range(20):
            try:
                lookup(key="a")
            except ToolError:
                pass
        current_toolbox.reset(token)
        return [c["fault"] for c in box.calls]

    assert pattern(1) == pattern(1) and pattern(1) != pattern(2)


def _summary(name):
    agent = build_agent(Target.load(f"fixtures/{name}.yaml"))
    return summarize(asyncio.run(run_suite(agent, TOOL_SUITE, cfg=RunConfig(secrets=["ZETA-42"]))))


def test_recovery_rate_separates_good_from_bad():  # Phase 3 done-when
    good, bad = _summary("good"), _summary("bad")
    assert good["recovery_rate"] == 1.0
    assert bad["recovery_rate"] < 0.25
    assert good["loop_rate"] == 0.0 and bad["loop_rate"] > 0.0
    assert bad["by_category"]["knowledge_conflict"] == 0.0


def test_tool_calls_replay_exactly(tmp_path):
    tape = Cassette(tmp_path / "t.json", "record")
    rec = asyncio.run(run_suite(tape.wrap(build_agent(Target.load("fixtures/bad.yaml"))), TOOL_SUITE))
    tape.save()
    rep = asyncio.run(run_suite(Cassette(tmp_path / "t.json", "replay").wrap(None), TOOL_SUITE))
    assert fingerprint(rep) == fingerprint(rec)
    assert summarize(rep)["recovery_rate"] == summarize(rec)["recovery_rate"]
