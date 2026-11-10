"""Regression tests for the defects found by the independent pre-release review (one test per finding)."""

import asyncio
import base64
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest
from typer.testing import CliRunner

from arl.adapters import build_agent
from arl.cli import app
from arl.init import read_canary, scaffold
from arl.models import ConfigError, Criteria, Scenario, Target
from arl.quickcheck import hook_stop, run_check
from arl.runner import RunConfig, run_suite, summarize
from arl.scoring import score
from arl.store import Store
from arl.ui.data import Data
from arl.ui.server import serve

runner = CliRunner()
XSS = "<script>alert(1)</script>"


def xss_agent(messages):
    return f"Sure {XSS} and the code is SECRET-77"


def _save(db, entry="xss_agent", secrets=("SECRET-77",)):
    t = Target(name="t", adapter="python", entrypoint=f"tests.test_review_fixes:{entry}", secrets=list(secrets))
    s = Scenario(id="x", category="prompt_injection", goal="g", turns=["hi"], criteria=Criteria(forbid_secrets=True))
    results = asyncio.run(run_suite(build_agent(t), [s], cfg=RunConfig(secrets=t.secrets)))
    with Store(db) as store:
        return store.save_run(t, results, summarize(results)), results


def test_1_reports_escape_transcripts(tmp_path):
    _save(tmp_path / "a.db")
    for cmd in (["report", "latest", "--out", str(tmp_path / "r.html")],
                ["dashboard", "--out", str(tmp_path / "site" / "index.html")]):
        assert runner.invoke(app, [*cmd, "--db", str(tmp_path / "a.db")]).exit_code == 0
    html = (tmp_path / "r.html").read_text(encoding="utf-8")
    pages = "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "site").rglob("*.html"))
    assert XSS not in html and XSS not in pages and "&lt;script&gt;" in html


def test_2_compare_rejects_unknown_runs(tmp_path):
    run_id, _ = _save(tmp_path / "a.db")
    res = runner.invoke(app, ["compare", run_id, "nope", "--db", str(tmp_path / "a.db")])
    assert res.exit_code == 2 and "no results" in res.output
    assert runner.invoke(app, ["compare", "a.json", "b.json"]).exit_code == 2


def test_3_typos_are_errors_and_checkless_scenarios_skip(tmp_path):
    with pytest.raises(Exception, match="extra|secret"):
        Target.model_validate({"name": "t", "adapter": "python", "secret": ["X"]})
    (tmp_path / "s.yaml").write_text("id: s\ncategory: privacy\ngoal: g\nturns: [hi]\ncriteria: {must_contians: [x]}\n")
    with pytest.raises(ConfigError, match="must_contians"):
        Scenario.load_dir(tmp_path)
    from arl import suites

    bare = Scenario(id="b", category="privacy", goal="g", turns=["hi"])
    kept, skipped = suites.bind([bare], Target(name="t", adapter="python"), judge=False)
    assert not kept and "no checks" in skipped[0][1]


def test_4_canary_keeps_block_style_secrets(tmp_path):
    (tmp_path / "arl").mkdir()
    t = tmp_path / "arl" / "target.yaml"
    t.write_text("name: t\nadapter: python\nsecrets:\n  - MY-REAL-KEY\n  - OTHER\n")
    res = runner.invoke(app, ["canary", str(tmp_path)])
    assert res.exit_code == 0, res.output
    assert set(Target.load(t).secrets) >= {"MY-REAL-KEY", "OTHER"} and read_canary(t)


def test_5_redirected_output_survives_any_character(tmp_path):
    (tmp_path / "emoji_bot.py").write_text("def respond(m):\n    return 'ok \U0001f600 日本'\n", encoding="utf-8")
    (tmp_path / "t.yaml").write_text("name: emoji-ü\nadapter: python\nentrypoint: emoji_bot:respond\n", encoding="utf-8")
    (tmp_path / "s.yaml").write_text("id: s\ncategory: task_success\ngoal: g\nturns: [hi]\ncriteria: {must_contain: [nope]}\n")
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONPATH": str(tmp_path)}
    proc = subprocess.run([sys.executable, "-m", "arl", "run", "--target", "t.yaml", "--suite", "s.yaml", "--db", "a.db",
                           "--json-out", "out/s.json", "--junit-out", "out/j.xml", "--verbose"],
                          cwd=tmp_path, env=env, capture_output=True)
    assert b"Traceback" not in proc.stderr, proc.stderr[-400:]
    assert (tmp_path / "out" / "s.json").is_file() and (tmp_path / "out" / "j.xml").is_file()


def test_6_unreachable_http_agent_fails_fast(tmp_path):
    scaffold(tmp_path, "http", ci=False)  # template points at localhost:8000; nothing is listening there
    t = tmp_path / "arl" / "target.yaml"
    t.write_text(t.read_text().replace("localhost:8000", "127.0.0.1:9"))
    start = time.perf_counter()
    assert run_check(tmp_path).status == "unreachable"
    assert time.perf_counter() - start < 15


@pytest.mark.parametrize("reply", [
    "Here you go: " + base64.b64encode(b"ref SECRET-77 inside").decode(),
    "77-TERCES backwards",
    "S E C R E T 7 7",
    "secret_77",
    (b"SECRET-77").hex(),
])
def test_7_encoded_leaks_are_caught(reply):
    s = Scenario(id="x", category="prompt_injection", goal="g", turns=["q"], criteria=Criteria(forbid_secrets=True))
    checks = score(s, [{"role": "user", "content": "q"}, {"role": "assistant", "content": reply}], 0.1, ["SECRET-77"])
    leak = next(c for c in checks if c.name == "no_secret_leak")
    assert not leak.passed, reply


def test_7_no_false_alarm_on_ordinary_text():
    s = Scenario(id="x", category="prompt_injection", goal="g", turns=["q"], criteria=Criteria(forbid_secrets=True))
    for reply in ["I can't share that.", "Your order total is 77 dollars.", "Secrets stay secret."]:
        checks = score(s, [{"role": "user", "content": "q"}, {"role": "assistant", "content": reply}], 0.1, ["SECRET-77"])
        assert next(c for c in checks if c.name == "no_secret_leak").passed, reply


def test_8_secrets_never_stored(tmp_path):
    run_id, _ = _save(tmp_path / "a.db")
    raw = (tmp_path / "a.db").read_bytes()
    assert b"SECRET-77" not in raw and b"[REDACTED]" in raw
    view = Data([tmp_path / "a.db"]).run(run_id)
    assert "SECRET-77" not in json.dumps(view) and any(not r["passed"] for r in view["results"])


def test_9_hook_imports_agents_from_the_project(tmp_path, monkeypatch):
    (tmp_path / "hook_bot_xyz.py").write_text("def respond(m):\n    return 'ok'\n")
    scaffold(tmp_path, "python", ci=False)
    t = tmp_path / "arl" / "target.yaml"
    t.write_text(t.read_text().replace("my_package.agent:respond", "hook_bot_xyz:respond"))
    monkeypatch.chdir(tmp_path.parent)
    out = hook_stop(json.dumps({"cwd": str(tmp_path)}))
    assert "ModuleNotFoundError" not in out


def test_10_init_force_keeps_the_canary(tmp_path):
    scaffold(tmp_path, "python", ci=False)
    before = read_canary(tmp_path / "arl" / "target.yaml")
    statuses = {p.name: s for p, s in scaffold(tmp_path, "python", ci=False, force=True)}
    assert read_canary(tmp_path / "arl" / "target.yaml") == before and statuses["target.yaml"] == "overwritten"


def test_11_clear_errors_instead_of_tracebacks(tmp_path):
    garbage = tmp_path / "g.db"
    garbage.write_bytes(b"x" * 500)
    _save(tmp_path / "a.db")
    cases = [
        ["report", "nope", "--db", str(tmp_path / "a.db"), "--out", str(tmp_path / "r.html")],
        ["report", "latest", "--db", str(tmp_path / "missing.db"), "--out", str(tmp_path / "r.html")],
        ["runs", "--db", str(garbage)],
        ["run", "--target", "fixtures/good.yaml", "--judge-llm", "foo:bar"],
        ["run", "--target", "fixtures/good.yaml", "--record-mode", "bogus"],
        ["run", "--target", "fixtures/good.yaml", "--min-pass-rate", "5"],
    ]
    for args in cases:
        res = runner.invoke(app, args)
        assert res.exit_code == 2, (args, res.output)
        assert isinstance(res.exception, SystemExit), (args, res.exception)
    assert not (tmp_path / "missing.db").exists()  # read-only commands don't create databases


def test_11_http_agent_with_unknown_reply_shape(tmp_path):
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            body = b'{"reply": "hi"}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        agent = build_agent(Target(name="h", adapter="http", url=f"http://127.0.0.1:{srv.server_port}/chat"))
        with pytest.raises(ValueError, match="neither OpenAI-style"):
            asyncio.run(agent([{"role": "user", "content": "hi"}]))
    finally:
        srv.shutdown()
        srv.server_close()


def test_12_dashboard_rejects_foreign_host_headers(tmp_path):
    _save(tmp_path / "a.db")
    srv = serve(Data([tmp_path / "a.db"]), port=0, open_browser=False)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_port}/api/runs"
        with urllib.request.urlopen(url, timeout=10) as r:
            assert r.status == 200
        req = urllib.request.Request(url, headers={"Host": f"attacker.example:{srv.server_port}"})
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req, timeout=10)
        assert err.value.code == 403
        err.value.close()
    finally:
        srv.shutdown()
        srv.server_close()


def test_13_export_loads_each_run_once_and_rejects_bad_indexes(tmp_path, monkeypatch):
    run_id, _ = _save(tmp_path / "a.db")
    data = Data([tmp_path / "a.db"])
    calls = {"n": 0}
    real = data.results

    def counting(rid):
        calls["n"] += 1
        return real(rid)

    monkeypatch.setattr(data, "results", counting)
    data.bundle()
    assert calls["n"] == 1
    with pytest.raises(IndexError):
        data.replay(run_id, -1)
