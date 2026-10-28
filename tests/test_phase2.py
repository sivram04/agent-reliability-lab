"""Phase 2: scenario library and simulated users."""

import asyncio
from collections import Counter

from arl.adapters import build_agent
from arl.cassette import Cassette
from arl.llm import build_llm
from arl.models import Scenario, Target
from arl.runner import RunConfig, fingerprint, run_one, run_suite, summarize

LIBRARY = Scenario.load_dir("scenarios/library")
FAKE_USER = "python:fixtures.fake_user:respond"


def _cfg(**kw):
    return RunConfig(user_llm=build_llm(FAKE_USER), secrets=["ZETA-42", "Secret discount code"], **kw)


def test_library_is_valid_and_unique():
    ids = [s.id for s in LIBRARY]
    assert len(ids) == len(set(ids))
    assert len(LIBRARY) >= 80
    assert set(Counter(s.category for s in LIBRARY)) >= {"task_success", "adversarial_user", "prompt_injection", "privacy"}


def test_simulated_user_reaches_goal_multi_turn():
    s = next(x for x in LIBRARY if x.id == "task-simuser-2")
    r = asyncio.run(run_one(build_agent(Target.load("fixtures/good.yaml")), s, 0, 0, _cfg()))
    assert r.stop_reason == "goal_met" and r.passed
    assert len(r.transcript) >= 4  # vague opener, agent asks, user supplies number, answer


def test_simulated_user_gives_up_on_bad_agent():
    s = next(x for x in LIBRARY if x.id == "task-simuser-2")
    r = asyncio.run(run_one(build_agent(Target.load("fixtures/bad.yaml")), s, 0, 0, _cfg()))
    assert not r.passed


def test_good_beats_bad_on_library():
    rates = {}
    for name in ("good", "bad"):
        results = asyncio.run(run_suite(build_agent(Target.load(f"fixtures/{name}.yaml")), LIBRARY, cfg=_cfg()))
        rates[name] = summarize(results)
    assert rates["good"]["pass_rate"] == 1.0
    assert rates["bad"]["pass_rate"] < 0.7
    assert rates["bad"]["by_category"]["prompt_injection"] < 0.5


def test_simulated_user_calls_are_recorded_and_replayed(tmp_path):
    sims = [s for s in LIBRARY if s.user_goal]
    tape = Cassette(tmp_path / "c.json", "record")
    cfg = _cfg()
    cfg.user_llm = tape.wrap(cfg.user_llm, "user")
    rec = asyncio.run(run_suite(tape.wrap(build_agent(Target.load("fixtures/good.yaml"))), sims, cfg=cfg))
    tape.save()

    replay = Cassette(tmp_path / "c.json", "replay")
    cfg2 = RunConfig(user_llm=replay.wrap(None, "user"), secrets=cfg.secrets)
    rep = asyncio.run(run_suite(replay.wrap(None), sims, cfg=cfg2))
    assert fingerprint(rep) == fingerprint(rec)


def test_multi_turn_transcripts_are_stored(tmp_path):
    from arl.store import Store

    target = Target.load("fixtures/good.yaml")
    sims = [s for s in LIBRARY if s.user_goal]
    results = asyncio.run(run_suite(build_agent(target), sims, cfg=_cfg()))
    store = Store(tmp_path / "r.db")
    run_id = store.save_run(target, results, summarize(results))
    loaded = store.load_results(run_id)
    store.close()
    assert fingerprint(loaded) == fingerprint(results)
    assert {r.stop_reason for r in loaded} <= {"goal_met", "gave_up", "max_turns"}
