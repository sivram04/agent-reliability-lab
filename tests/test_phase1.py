"""Phase 1 done-when: the same scenario runs against every adapter type and replays exactly."""

import asyncio

import pytest

from arl.adapters import build_agent
from arl.cassette import Cassette, CassetteMiss
from arl.models import Scenario, Target
from arl.runner import fingerprint, run_suite, summarize
from fixtures.http_server import serve_in_thread

SUITE = Scenario.load_dir("scenarios/smoke")


@pytest.fixture(scope="module")
def http_target():
    server = serve_in_thread()
    yield Target(name="orderbot-good-http", adapter="http",
                 url=f"http://127.0.0.1:{server.server_address[1]}/chat")
    server.shutdown()


def _targets(http_target):
    return {
        "python": Target.load("fixtures/good.yaml"),
        "http": http_target,
        "langgraph": Target.load("fixtures/good_langgraph.yaml"),
        "mcp": Target.load("fixtures/good_mcp.yaml"),
    }


def _run(agent, repeats=1):
    return asyncio.run(run_suite(agent, SUITE, repeats=repeats))


def test_all_adapters_give_identical_results(http_target):
    prints = {}
    # Equivalence, not speed: MCP spawns a server per call, which is slow under load on Windows.
    suite = [s.model_copy(update={"criteria": s.criteria.model_copy(update={"max_latency_s": None})}) for s in SUITE]
    for kind, target in _targets(http_target).items():
        results = asyncio.run(run_suite(build_agent(target), suite))
        assert summarize(results)["pass_rate"] == 1.0, kind
        # Only the in-process python adapter can observe @tool calls; compare conversations.
        prints[kind] = fingerprint([r.model_copy(update={"tool_calls": []}) for r in results])
    assert all(p == prints["python"] for p in prints.values())


def _explode(messages):
    raise AssertionError("replay must not call the agent")


def test_replay_matches_recording_without_calling_agent(tmp_path):
    path = tmp_path / "bad.json"
    rec = Cassette(path, "record")
    recorded = _run(rec.wrap(build_agent(Target.load("fixtures/bad.yaml"))), repeats=2)
    rec.save()

    replayed = _run(Cassette(path, "replay").wrap(_explode), repeats=2)
    assert fingerprint(replayed) == fingerprint(recorded)
    # The bad agent's crash is reproduced with the same error text.
    assert any(r.error and r.error.startswith("IndexError") for r in replayed)


def test_replay_fails_loudly_on_changed_request(tmp_path):
    path = tmp_path / "good.json"
    rec = Cassette(path, "record")
    _run(rec.wrap(build_agent(Target.load("fixtures/good.yaml"))))
    rec.save()

    changed = [s.model_copy(update={"turns": [t + "!" for t in s.turns]}) for s in SUITE]
    results = asyncio.run(run_suite(Cassette(path, "replay").wrap(_explode), changed))
    assert all(r.error and r.error.startswith(CassetteMiss.__name__) for r in results)


def test_spans_recorded_per_turn():
    results = _run(build_agent(Target.load("fixtures/good.yaml")))
    multi = next(r for r in results if r.scenario_id == "multi-step-order")
    names = [s["name"] for s in multi.spans]
    assert names.count("agent.turn") == 2 and names[-1] == "scenario"
