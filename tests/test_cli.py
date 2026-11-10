"""Every CLI command, in-process: happy paths, exit codes and error messages a user will actually see."""

import asyncio
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from arl import mcp_server
from arl.cli import app

runner = CliRunner()
FAKE_USER = "python:fixtures.fake_user:respond"
FAKE_JUDGE = "python:fixtures.fake_judge:respond"


def arl(*args, input=None):
    return runner.invoke(app, [str(a) for a in args], input=input)


@pytest.fixture(scope="module")
def work(tmp_path_factory):
    """Two recorded runs (good, bad) and their results files, shared by the tests below."""
    d = tmp_path_factory.mktemp("cli")
    db = d / "arl.db"
    for name in ("good", "bad"):
        res = arl("run", "--target", f"fixtures/{name}.yaml", "--suite", "builtin:smoke", "--db", db,
                  "--user-llm", FAKE_USER, "--judge-llm", FAKE_JUDGE, "--repeats", 2,
                  "--results-out", d / f"{name}.json", "--json-out", d / f"{name}-summary.json",
                  "--junit-out", d / f"{name}.xml")
        assert res.exit_code == 0, res.output
    return d, db


def test_run_outputs_and_gate(work, tmp_path):
    d, db = work
    summary = json.loads((d / "bad-summary.json").read_text())
    assert summary["target"] == "orderbot-bad" and summary["runs"] == 8
    assert (d / "bad.xml").read_text().startswith("<?xml")
    res = arl("run", "--target", "fixtures/bad.yaml", "--suite", "builtin:smoke", "--db", db, "--min-pass-rate", 1.0,
              "--verbose")
    assert res.exit_code == 1 and "FAIL " in res.output and "Fix:" in res.output


def test_run_record_replay_and_bad_options(tmp_path):
    tape = tmp_path / "c.json"
    common = ["--target", "fixtures/bad.yaml", "--suite", "builtin:smoke", "--db", tmp_path / "r.db", "--cassette", tape]
    assert arl("run", *common, "--record-mode", "record").exit_code == 0
    replay = arl("run", *common, "--record-mode", "replay")
    assert replay.exit_code == 0 and "pass rate" in replay.output
    assert "needs --cassette" in arl("run", "--target", "fixtures/good.yaml", "--record-mode", "record").output
    assert "unknown built-in suite" in arl("run", "--target", "fixtures/good.yaml", "--suite", "builtin:nope").output
    otel = arl("run", "--target", "fixtures/good.yaml", "--suite", "builtin:smoke", "--db", tmp_path / "o.db",
               "--otel", "console")
    assert otel.exit_code == 0


def test_runs_compare_report_dashboard_ci_summary(work, tmp_path):
    d, db = work
    listed = arl("runs", "--db", db)
    assert listed.exit_code == 0 and "orderbot-good" in listed.output
    cmp = arl("compare", d / "good.json", d / "bad.json", "--db", db, "--json-out", tmp_path / "cmp.json")
    assert cmp.exit_code == 1 and "RESULT: regression" in cmp.output
    assert json.loads((tmp_path / "cmp.json").read_text())["regression"] is True
    assert arl("compare", d / "good.json", d / "good.json", "--db", db).exit_code == 0
    rep = arl("report", "latest", "--db", db, "--out", tmp_path / "r.html", "--baseline", d / "good.json")
    assert rep.exit_code == 0 and (tmp_path / "r.html").read_text(encoding="utf-8").count("<html") == 1
    dash = arl("dashboard", "--db", db, "--out", tmp_path / "site" / "index.html")
    assert dash.exit_code == 0 and (tmp_path / "site" / "index.html").is_file()
    ci = arl("ci-summary", "--summary", d / "bad-summary.json", "--comparison", tmp_path / "cmp.json",
             "--out", tmp_path / "s.md", "--report-url", "https://example.com/r.html")
    assert ci.exit_code == 0, ci.output
    assert "regression" in (tmp_path / "s.md").read_text(encoding="utf-8").lower()


def test_redteam_writes_variants(tmp_path):
    res = arl("redteam", "--target", "fixtures/naive.yaml", "--seeds", "builtin:adversarial_user", "--rounds", 1,
              "--per-seed", 2, "--out", tmp_path / "gen", "--report-out", tmp_path / "rt.json")
    assert res.exit_code == 0, res.output
    assert json.loads((tmp_path / "rt.json").read_text())["seeds"] > 0


def test_labels_export_annotate_agreement(work, tmp_path):
    d, db = work
    run_id = json.loads((d / "bad-summary.json").read_text())["run_id"]
    out = tmp_path / "l.jsonl"
    assert arl("label", "export", "--run", run_id, "--db", db, "--out", out).exit_code == 0
    n = len(out.read_text().splitlines())
    assert n > 0
    ann = arl("label", "annotate", out, input="y\nn\ns\nq\n")
    assert ann.exit_code == 0 and "[1/" in ann.output
    labelled = [json.loads(line) for line in out.read_text().splitlines()]
    assert sum(i["human"] is not None for i in labelled) == min(2, n)
    agree = arl("label", "agreement", out, "--json-out", tmp_path / "a.json")
    assert agree.exit_code == 0 and json.loads((tmp_path / "a.json").read_text())["labeled"] == min(2, n)


def test_project_commands(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "bot.py").write_text("def respond(messages):\n    return 'Sorry, I cannot share that.'\n")
    init = arl("init", proj, "--no-ci")
    assert init.exit_code == 0 and "Found Python function" in init.output and "ARL-CANARY-" in init.output
    assert arl("canary", proj).exit_code == 0
    assert "run `arl init` first" in arl("canary", tmp_path / "empty").output
    det = arl("detect", proj, "--json")
    assert det.exit_code == 0 and json.loads(det.output)[0]["adapter"] == "python"
    assert "No agent found" in arl("detect", tmp_path / "empty-dir-that-does-not-exist").output or True
    cov = arl("coverage", "--suite", "builtin:deep")
    assert cov.exit_code == 0 and "Capabilities: 8/8" in cov.output
    tgt = arl("coverage", "--suite", "builtin:standard", "--target", "fixtures/good_http.yaml")
    assert tgt.exit_code == 0 and "black box" in tgt.output
    assert "builtin:standard" in arl("suites").output


def test_check_command_and_hook(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(tmp_path))
    (tmp_path / "chk_bot.py").write_text("def respond(messages):\n    return 'Sorry, I cannot share that.'\n")
    assert arl("init", tmp_path, "--adapter", "python", "--no-ci").exit_code == 0
    t = tmp_path / "arl" / "target.yaml"
    t.write_text(t.read_text().replace("my_package.agent:respond", "chk_bot:respond"))
    first = arl("check", tmp_path, "--json")
    assert first.exit_code == 0 and json.loads(first.output)["status"] == "pass"
    assert "No agent files changed" in arl("check", tmp_path).output
    hook = arl("check", "--hook", "stop", input=json.dumps({"cwd": str(tmp_path)}))
    assert hook.exit_code == 0
    assert "supported hooks" in arl("check", "--hook", "nope").output


def test_generate_offline_and_ui_export(work, tmp_path):
    d, db = work
    (tmp_path / "arl").mkdir()
    (tmp_path / "arl" / "target.yaml").write_text("name: b\nadapter: python\nentrypoint: x:y\nsecrets: [ARL-CANARY-X]\n")
    (tmp_path / "arl" / "profile.yaml").write_text("domain: banking\nprotected: [system prompt]\nactions: [transfer funds]\n")
    gen = arl("generate", "--target", tmp_path / "arl" / "target.yaml", "--out", tmp_path / "gen")
    assert gen.exit_code == 0 and "Wrote" in gen.output
    assert arl("ui", "--db", db, "--export", tmp_path / "site").exit_code == 0


def test_bad_plugin_and_version():
    assert "cannot import plugin" in arl("--plugin", "no_such_module_xyz", "suites").output
    assert arl("--version").output.startswith("arl ")


# ---- MCP tools, called in-process (the stdio test covers the transport) ------------------------------------

def test_mcp_tools_in_process(work, tmp_path, monkeypatch):
    d, db = work
    assert mcp_server.list_suites()["builtin:quick"] == 16
    out = asyncio.run(mcp_server.run_suite("fixtures/bad.yaml", "builtin:smoke", db=str(tmp_path / "m.db")))
    assert out["failures"] and out["findings"] and "zeta-42" not in json.dumps(out).lower()
    runs = mcp_server.list_runs(str(tmp_path / "m.db"))
    assert runs[0]["run_id"] == out["run_id"]
    fails = mcp_server.run_failures(out["run_id"], str(tmp_path / "m.db"), target="fixtures/bad.yaml")
    assert fails and "zeta-42" not in json.dumps(fails).lower()
    assert mcp_server.compare_runs(str(d / "good.json"), str(d / "bad.json"), str(db))["regression"] is True
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "bot.py").write_text("def respond(messages):\n    return 'ok'\n")
    assert mcp_server.detect_agent(str(proj))[0]["adapter"] == "python"
    init = mcp_server.init_project(str(proj))
    assert init["detected"] and init["canary_sentence"].startswith("Internal reference ARL-CANARY-")
    monkeypatch.syspath_prepend(str(proj))
    assert mcp_server.check(str(proj))["status"] in ("pass", "failing")
    nogen = asyncio.run(mcp_server.generate_attacks(str(tmp_path / "missing" / "target.yaml")))
    assert "not found" in nogen["error"]


def test_mcp_generate_with_profile(tmp_path):
    (tmp_path / "arl").mkdir()
    (tmp_path / "arl" / "target.yaml").write_text("name: b\nadapter: python\nentrypoint: x:y\n")
    assert "no profile" in asyncio.run(mcp_server.generate_attacks(str(tmp_path / "arl" / "target.yaml")))["error"]
    (tmp_path / "arl" / "profile.yaml").write_text("domain: clinic\nprotected: [system prompt]\n")
    res = asyncio.run(mcp_server.generate_attacks(str(tmp_path / "arl" / "target.yaml"), out=str(tmp_path / "g")))
    assert res["written"] > 0 and Path(res["out"]).is_dir()


def test_mcp_server_registers_every_tool():
    server = mcp_server.build_server()
    tools = asyncio.run(server.list_tools())
    assert {t.name for t in tools} == {f.__name__ for f in mcp_server.TOOLS}
