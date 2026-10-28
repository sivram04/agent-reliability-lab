import asyncio

from arl.adapters import build_agent
from arl.models import Criteria, Scenario, Target
from arl.runner import run_suite, summarize
from arl.scoring import score
from arl.store import Store


def _run(target_file: str, repeats: int = 2) -> dict:
    agent = build_agent(Target.load(target_file))
    results = asyncio.run(run_suite(agent, Scenario.load_dir("scenarios/smoke"), repeats=repeats))
    return summarize(results)


def test_good_agent_passes_smoke_suite():
    assert _run("fixtures/good.yaml")["pass_rate"] == 1.0


def test_known_bad_agent_fails():  # N3
    s = _run("fixtures/bad.yaml")
    assert s["pass_rate"] < 0.5
    assert s["by_category"]["prompt_injection"] == 0.0
    assert s["by_category"]["privacy"] == 0.0


def test_empty_suite_is_a_pass():
    agent = build_agent(Target.load("fixtures/good.yaml"))
    assert summarize(asyncio.run(run_suite(agent, [])))["pass_rate"] == 1.0


def test_forbidden_check_is_case_insensitive():
    sc = Scenario(id="x", category="privacy", goal="g", turns=["hi"],
                  criteria=Criteria(must_not_contain=["zeta-42"]))
    checks = score(sc, [{"role": "assistant", "content": "code ZETA-42"}], 0.1)
    assert not checks[0].passed


def test_store_roundtrip(tmp_path):
    store = Store(tmp_path / "t.db")
    run_id = store.save_run(Target.load("fixtures/good.yaml"), [], {"runs": 0, "passed": 0, "pass_rate": 1.0})
    assert store.list_runs()[0][0] == run_id
    store.close()
