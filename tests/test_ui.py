"""`arl ui`: JSON API, static export, and safety of rendering attack transcripts."""

import asyncio
import json
import re
import threading
import urllib.request
from pathlib import Path

import pytest
from typer.testing import CliRunner

from arl import suites
from arl.adapters import build_agent
from arl.cli import app
from arl.models import Target
from arl.runner import RunConfig, run_suite, summarize
from arl.store import Store
from arl.ui.data import Data
from arl.ui.server import STATIC, export, serve


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("ui") / "arl.db"
    store = Store(path)
    for name in ("good", "bad"):
        target = Target.load(f"fixtures/{name}.yaml")
        scenarios, _ = suites.bind(suites.load("builtin:library"), target, judge=False)
        results = asyncio.run(run_suite(build_agent(target), scenarios, cfg=RunConfig(secrets=target.secrets)))
        store.save_run(target, results, summarize(results), "builtin:library")
    store.close()
    return path


@pytest.fixture(scope="module")
def server(db):
    srv = serve(Data([db]), port=0, open_browser=False)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def _get(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.status, r.headers.get("Content-Type"), r.read()


def test_api_runs_run_replay_compare(server):
    _, ctype, body = _get(f"{server}/api/runs")
    runs = json.loads(body)
    assert ctype == "application/json" and {r["target"] for r in runs} == {"orderbot-good", "orderbot-bad"}
    bad = next(r for r in runs if r["target"] == "orderbot-bad")
    run = json.loads(_get(f"{server}/api/runs/{bad['id']}")[2])
    assert run["findings"] and run["headline"] and run["coverage"]["capability"]["covered"]
    failing = next(r for r in run["results"] if not r["passed"])
    replay = json.loads(_get(f"{server}/api/runs/{bad['id']}/replay/{failing['idx']}")[2])
    assert replay["transcript"] and replay["checks"]
    good = next(r for r in runs if r["target"] == "orderbot-good")
    cmp = json.loads(_get(f"{server}/api/compare?base={good['id']}&new={bad['id']}")[2])
    assert cmp["regression"] is True


def test_static_files_and_errors(server):
    status, ctype, html = _get(f"{server}/")
    assert status == 200 and "text/html" in ctype and b"static/app.js" in html
    for bad in ("/static/../server.py", "/api/runs/nope", "/nope"):
        with pytest.raises(urllib.error.HTTPError) as err:
            _get(server + bad)
        assert err.value.code == 404


def test_every_dynamic_value_is_escaped():
    """Transcripts contain real attack payloads (<script>, <iframe>): the app must escape all of them."""
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "const esc =" in js
    # Lines marked as plain text (document.title) or escaped later are reviewed exceptions.
    js = "\n".join(line for line in js.splitlines() if "// text-only" not in line and "// escaped below" not in line)
    # Data fields interpolated into HTML templates must go through esc(), label(), pct() or a number format.
    raw = re.findall(r"\$\{\s*(?:r|f|row|run|c|e|s|p|m)\.(?:content|text|scenario|goal|error|title|why|fix|example_user|"
                     r"example_reply|detail|name|tool|target|version|suite|source|headline|id)\s*\}", js)
    assert raw == [], raw


def test_export_is_self_contained_and_escapes_script_tags(db, tmp_path):
    index = export(Data([db]), tmp_path / "site")
    html = index.read_text(encoding="utf-8")
    data_js = (tmp_path / "site" / "static" / "data.js").read_text(encoding="utf-8")
    assert "static/data.js" in html and (tmp_path / "site" / "static" / "app.js").is_file()
    assert data_js.startswith("window.ARL_DATA = ") and "</script" not in data_js.lower()
    no_ns = re.sub(r"xmlns=['\"][^'\"]+['\"]", "", html)
    assert "http://" not in no_ns and "https://" not in no_ns  # no external requests: works offline


def test_cli_ui_export_and_missing_db(db, tmp_path):
    runner = CliRunner()
    res = runner.invoke(app, ["ui", "--db", str(db), "--export", str(tmp_path / "out")])
    assert res.exit_code == 0 and (tmp_path / "out" / "index.html").is_file()
    res = runner.invoke(app, ["ui", "--db", str(tmp_path / "missing.db"), "--no-open"])
    assert res.exit_code != 0 and "no result database" in res.output


def test_package_ships_the_static_app():
    assert {p.name for p in STATIC.iterdir()} >= {"index.html", "app.js", "app.css"}
    assert Path(STATIC / "index.html").read_text(encoding="utf-8").count("<script") == 1


def test_bundled_font_is_served_licensed_and_exported(server, db, tmp_path):
    status, ctype, body = _get(f"{server}/static/D-DIN-Bold.woff2")
    assert status == 200 and ctype == "font/woff2" and body[:4] == b"wOF2"
    assert b"SIL OPEN FONT LICENSE" in _get(f"{server}/static/D-DIN-LICENSE.txt")[2].upper()
    export(Data([db]), tmp_path / "site")
    assert {"D-DIN.woff2", "D-DIN-Bold.woff2", "D-DIN-LICENSE.txt"} <= {p.name for p in (tmp_path / "site" / "static").iterdir()}
