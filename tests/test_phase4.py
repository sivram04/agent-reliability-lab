"""Phase 4: judges, agreement, statistics."""

import asyncio

from arl.adapters import build_agent
from arl.judges import parse_verdict
from arl.labels import agreement, export, read
from arl.llm import build_llm
from arl.models import Scenario, Target
from arl.runner import RunConfig, run_suite, summarize
from arl.stats import bootstrap_ci, cohen_kappa, compare, wilson_ci
from arl.store import Store

LIBRARY = Scenario.load_dir("scenarios/library")
SECRETS = ["ZETA-42", "Secret discount code"]


def _run(name, repeats=1, judge=True):
    cfg = RunConfig(repeats=repeats, secrets=SECRETS,
                    user_llm=build_llm("python:fixtures.fake_user:respond"),
                    judge_llm=build_llm("python:fixtures.fake_judge:respond") if judge else None)
    return asyncio.run(run_suite(build_agent(Target.load(f"fixtures/{name}.yaml")), LIBRARY, cfg=cfg))


def test_parse_verdict_variants():
    assert parse_verdict('{"verdict": "pass", "reason": "ok"}') == (True, "ok")
    assert parse_verdict('Sure!\n```json\n{"verdict": "FAIL", "reason": "leak"}\n```')[0] is False
    assert parse_verdict("PASS")[0] is True


def test_judges_run_only_after_deterministic_checks_pass():
    results = _run("bad")
    for r in results:
        judged = any(c.name.startswith("judge:") for c in r.checks)
        deterministic_ok = r.error is None and all(c.passed for c in r.checks if not c.name.startswith("judge:"))
        assert judged == deterministic_ok


def test_good_agent_passes_judges():
    s = summarize(_run("good"))
    assert s["pass_rate"] == 1.0 and s["hallucination_rate"] == 0.0


def test_wilson_and_bootstrap():
    lo, hi = wilson_ci(8, 10)
    assert 0.44 < lo < 0.5 and 0.94 < hi < 0.97
    blo, bhi = bootstrap_ci([1] * 8 + [0] * 2)
    assert blo < 0.8 < bhi
    assert wilson_ci(0, 0) == (0.0, 1.0)


def test_bad_agent_regression_is_significant():  # Phase 4 done-when
    good, bad = _run("good", repeats=3), _run("bad", repeats=3)
    report = compare(good, bad)
    assert report["regression"]
    overall = report["rows"][0]
    assert overall["metric"] == "pass_rate" and overall["p_value"] < 1e-6
    assert overall["new_ci"][1] < overall["base_ci"][0]  # intervals do not overlap


def test_identical_versions_are_not_a_regression():
    a, b = _run("good", judge=False), _run("good", judge=False)
    assert not compare(a, b)["regression"]


def test_cohen_kappa():
    assert cohen_kappa([True, False, True, False], [True, False, True, False]) == 1.0
    assert abs(cohen_kappa([True, True, False, False], [True, False, True, False])) < 1e-9


def test_label_export_and_agreement(tmp_path):
    target = Target.load("fixtures/bad.yaml")
    results = _run("bad")
    store = Store(tmp_path / "r.db")
    run_id = store.save_run(target, results, summarize(results))
    n = export(store, run_id, tmp_path / "l.jsonl")
    store.close()
    items = read(tmp_path / "l.jsonl")
    assert n == len(items) > 0 and all(i["human"] is None for i in items)
    for i in items:  # pretend a human agreed with the judge on all but one item
        i["human"] = i["judge"]
    items[0]["human"] = not items[0]["judge"]
    report = agreement(items)
    assert report["labeled"] == n and report["agreement"] == (n - 1) / n
