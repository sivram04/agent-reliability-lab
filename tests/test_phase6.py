"""Phase 6: reports, dashboard, CI gate."""

import json
import subprocess
import sys

import pytest

ARL = [sys.executable, "-m", "arl.cli"]
USER = ["--user-llm", "python:fixtures.fake_user:respond"]


def _arl(*args, check=True):
    return subprocess.run([*ARL, *args], capture_output=True, text=True, check=check)


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    d = tmp_path_factory.mktemp("ci")
    db = str(d / "arl.db")
    _arl("run", "--target", "fixtures/good.yaml", "--suite", "scenarios/library", "--repeats", "2", *USER,
         "--db", db, "--results-out", str(d / "base.json"))
    _arl("run", "--target", "fixtures/good_v2.yaml", "--suite", "scenarios/library", "--repeats", "2", *USER,
         "--db", db, "--results-out", str(d / "v2.json"), "--json-out", str(d / "v2-summary.json"))
    return d, db


def test_gate_blocks_regressed_version(runs):  # Phase 6 done-when (locally)
    d, db = runs
    blocked = _arl("compare", str(d / "base.json"), str(d / "v2.json"), "--json-out", str(d / "cmp.json"), check=False)
    assert blocked.returncode == 1 and "REGRESSION" in blocked.stdout
    same = _arl("compare", str(d / "base.json"), str(d / "base.json"), check=False)
    assert same.returncode == 0


def test_ci_summary_markdown(runs):
    d, _ = runs
    _arl("compare", str(d / "base.json"), str(d / "v2.json"), "--json-out", str(d / "cmp.json"), check=False)
    out = _arl("ci-summary", "--summary", str(d / "v2-summary.json"), "--comparison", str(d / "cmp.json"),
               "--out", str(d / "c.md")).stdout
    assert "Blocked: significant regression" in out and "pass_rate[tool_chaos] :x:" in out


def test_report_has_replayable_failures(runs):
    d, db = runs
    _arl("report", "latest", "--db", db, "--out", str(d / "r.html"), "--baseline", str(d / "base.json"))
    html = (d / "r.html").read_text(encoding="utf-8")
    assert "orderbot-good" in html and "regression" in html
    assert "simulated upstream error" in html  # the tool step that explains the failure
    data = json.loads((d / "r.json").read_text(encoding="utf-8"))
    assert len(data["results"]) == data["summary"]["runs"]


def test_dashboard_lists_versions(runs):
    d, db = runs
    _arl("dashboard", "--db", db, "--out", str(d / "dash" / "index.html"))
    html = (d / "dash" / "index.html").read_text(encoding="utf-8")
    assert "orderbot-good@1" in html and "orderbot-good@2" in html
    assert len(list((d / "dash" / "runs").glob("*.html"))) == 2
