"""Native LLM providers and token/cost accounting, against local stub servers."""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from arl import usage
from arl.adapters import build_agent
from arl.llm import build_llm
from arl.models import Criteria, Scenario, Target
from arl.runner import RunConfig, run_suite, summarize

SEEN: list[dict] = []


class Stub(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SEEN.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
        if self.path == "/v1/messages":  # Anthropic
            out = {"content": [{"type": "text", "text": "hello from claude"}],
                   "usage": {"input_tokens": 11, "output_tokens": 4}}
        else:  # OpenAI-compatible
            out = {"model": body.get("model"), "choices": [{"message": {"content": "order shipped"}}],
                   "usage": {"prompt_tokens": 20, "completion_tokens": 5}}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def stub():
    server = HTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def _metered(llm, messages):
    meter: dict = {}

    async def go():
        usage.current_usage.set(meter)
        return await llm(messages)

    return asyncio.run(go()), meter


def test_anthropic_moves_system_prompt_and_records_tokens(stub, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", stub)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    text, meter = _metered(build_llm("anthropic:claude-test", role="judge"),
                           [{"role": "system", "content": "be strict"}, {"role": "user", "content": "hi"}])
    req = SEEN[-1]
    assert text == "hello from claude"
    assert req["body"]["system"] == "be strict" and all(m["role"] != "system" for m in req["body"]["messages"])
    assert req["headers"]["x-api-key"] == "test-key"
    assert meter["judge"]["input_tokens"] == 11 and meter["judge"]["output_tokens"] == 4


def test_ollama_is_free_and_unauthenticated(stub, monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", stub)
    text, meter = _metered(build_llm("ollama:llama3.1", role="user"), [{"role": "user", "content": "hi"}])
    assert text == "order shipped"
    assert "authorization" not in SEEN[-1]["headers"]
    assert meter["user"]["cost_usd"] == 0.0


def test_unknown_price_stays_none_and_known_price_is_used():
    assert usage.price("mystery-model", 1000, 1000) is None
    usage.load_prices({"priced": {"input": 1.0, "output": 2.0}})
    assert usage.price("priced", 1_000_000, 500_000) == pytest.approx(2.0)


def test_bad_specs_are_rejected():
    with pytest.raises(ValueError, match="needs a model"):
        build_llm("gemini")
    with pytest.raises(ValueError, match="unknown LLM spec"):
        build_llm("nope:model")


def test_run_summary_reports_agent_tokens_and_cost(stub):
    target = Target(name="stub", adapter="http", url=f"{stub}/v1/chat/completions", model="stub-model",
                    prices={"stub-model": {"input": 1.0, "output": 1.0}})
    usage.load_prices(target.prices)
    scenario = Scenario(id="s1", category="task_success", goal="g", turns=["where is my order?"],
                        criteria=Criteria(must_contain=["shipped"]))
    results = asyncio.run(run_suite(build_agent(target), [scenario, scenario], cfg=RunConfig(concurrency=2)))
    s = summarize(results)
    assert s["pass_rate"] == 1.0
    assert s["usage"]["agent"] == {"calls": 2, "input_tokens": 40, "output_tokens": 10,
                                   "cost_usd": pytest.approx(50 / 1e6)}
    assert s["usage"]["all"]["calls"] == 2


def test_dropped_connections_are_retried(monkeypatch):
    import urllib.error

    from arl import llm as llm_mod

    calls = {"n": 0}

    def flaky(url, body, headers):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.URLError(ConnectionResetError(10054, "forcibly closed"))
        return {"choices": [{"message": {"content": "ok"}}], "usage": {}}

    async def no_sleep(_):
        return None

    monkeypatch.setattr(llm_mod, "_post_json", flaky)
    monkeypatch.setattr(llm_mod.asyncio, "sleep", no_sleep)
    out = asyncio.run(llm_mod.openai_client("http://x", "m", "k")([{"role": "user", "content": "hi"}]))
    assert out == "ok" and calls["n"] == 3


def test_http_agent_retries_dropped_connections(monkeypatch):
    import urllib.error
    import urllib.request

    from arl import adapters

    calls = {"n": 0}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"choices": [{"message": {"content": "shipped"}}]}'

    def flaky(req, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionResetError(10054, "forcibly closed")
        return Resp()

    async def no_sleep(_):
        return None

    monkeypatch.setattr(urllib.request, "urlopen", flaky)
    monkeypatch.setattr(adapters.asyncio, "sleep", no_sleep)
    agent = build_agent(Target(name="h", adapter="http", url="http://x/v1/chat/completions"))
    assert asyncio.run(agent([{"role": "user", "content": "hi"}])) == "shipped" and calls["n"] == 3


def test_only_http_urls_are_accepted(monkeypatch):
    from pydantic import ValidationError

    for bad in ("file:///etc/passwd", "ftp://x/y", "gopher://x"):
        with pytest.raises(ValidationError, match="http"):
            Target(name="t", adapter="http", url=bad)
        with pytest.raises(ValueError, match="http"):
            build_llm("openai") if monkeypatch.setenv("ARL_LLM_BASE_URL", bad) is None else None
    assert Target(name="t", adapter="http", url="HTTPS://example.com/chat").url
