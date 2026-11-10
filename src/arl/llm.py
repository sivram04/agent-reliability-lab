"""LLM clients for the lab's own models (simulated users, judges, generator).

All of them share the agent call shape: `await llm(messages) -> str`, so the
same cassettes record and replay them.

Spec strings:
    openai                  OpenAI-compatible endpoint from env vars:
                            ARL_LLM_BASE_URL (default: http://localhost:8000/v1),
                            ARL_LLM_MODEL, ARL_LLM_API_KEY.
    openai:MODEL            api.openai.com, key from OPENAI_API_KEY
    anthropic:MODEL         Anthropic Messages API, key from ANTHROPIC_API_KEY
    gemini:MODEL            Gemini's OpenAI-compatible endpoint, key from GEMINI_API_KEY
    groq:MODEL              Groq, key from GROQ_API_KEY
    openrouter:MODEL        OpenRouter, key from OPENROUTER_API_KEY
    ollama:MODEL            local Ollama (OLLAMA_HOST, default http://localhost:11434)
    python:module:function  a local function, sync or async (used for offline fixtures).

Rate limiting: ARL_LLM_CONCURRENCY (parallel calls, default 2) and ARL_LLM_RPM
(requests per minute, unset = no pacing). 429 and 5xx responses are retried with backoff.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import os
import random
import urllib.error
import urllib.request
from collections.abc import Awaitable, Callable

from . import usage

LLM = Callable[[list[dict]], Awaitable[str]]

# OpenAI-compatible hosted providers: base URL and the env var holding the key.
OPENAI_COMPATIBLE = {
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
}
PROVIDERS = sorted([*OPENAI_COMPATIBLE, "anthropic", "ollama"])
RETRY_CODES = (429, 500, 502, 503, 529)

# Free tiers have tight rate limits; every lab LLM call shares this gate (N2).
_gate: asyncio.Semaphore | None = None


def _semaphore() -> asyncio.Semaphore:
    global _gate
    if _gate is None:
        _gate = asyncio.Semaphore(int(os.environ.get("ARL_LLM_CONCURRENCY", "2")))
    return _gate


_last_call = 0.0


async def _pace() -> None:
    """Space calls to ARL_LLM_RPM requests per minute (unset = no pacing). Called while
    holding the gate, so waits are serialised across concurrent callers."""
    global _last_call
    rpm = float(os.environ.get("ARL_LLM_RPM", "0") or 0)
    if rpm > 0:
        loop = asyncio.get_running_loop()
        wait = _last_call + 60.0 / rpm - loop.time()
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call = loop.time()


def _check_url(url: str) -> str:
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError(f"LLM endpoint must be http:// or https:// (got {url[:40]!r})")
    return url


def _post_json(url: str, body: dict, headers: dict) -> dict:
    # nosec B310 below: the scheme is checked by _check_url when the client is built.
    req = urllib.request.Request(url, data=json.dumps(body).encode(),  # nosec B310
                                 headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=60) as resp:  # nosec B310 - scheme checked by _check_url
        return json.loads(resp.read())


Post = Callable[[list[dict]], tuple[str, int, int]]  # -> (text, input_tokens, output_tokens)


def _client(post: Post, model: str, role: str, max_retries: int) -> LLM:
    async def call(messages: list[dict]) -> str:
        async with _semaphore():
            for attempt in range(max_retries):
                await _pace()
                try:
                    text, tin, tout = await asyncio.to_thread(post, messages)
                    usage.record(role, model, tin, tout)
                    return text
                except urllib.error.HTTPError as exc:
                    exc.close()  # release the connection before retrying or re-raising
                    if exc.code not in RETRY_CODES or attempt == max_retries - 1:
                        raise
                    # Per-minute free-tier limits reset within a minute: back off up to 60 s.
                    await asyncio.sleep(min(60, 2 ** (attempt + 1)) + random.random())
                except (urllib.error.URLError, ConnectionError, TimeoutError):
                    # Dropped connections and timeouts are transient on long runs; retry them too.
                    if attempt == max_retries - 1:
                        raise
                    await asyncio.sleep(min(30, 2 ** attempt) + random.random())
        raise RuntimeError("unreachable")

    return call


def openai_client(
    base_url: str | None = None, model: str | None = None, api_key: str | None = None,
    temperature: float = 0.7, max_retries: int = 8, role: str = "lab", price_model: str | None = None,
) -> LLM:
    base = _check_url((base_url or os.environ.get("ARL_LLM_BASE_URL", "http://localhost:8000/v1")).rstrip("/"))
    model = model or os.environ.get("ARL_LLM_MODEL", "llama-3.1-8b-instant")
    key = api_key if api_key is not None else os.environ.get("ARL_LLM_API_KEY", "")

    def post(messages: list[dict]) -> tuple[str, int, int]:
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        body = _post_json(f"{base}/chat/completions",
                          {"model": model, "messages": messages, "temperature": temperature}, headers)
        u = body.get("usage") or {}
        return (body["choices"][0]["message"]["content"] or "",
                u.get("prompt_tokens", 0), u.get("completion_tokens", 0))

    return _client(post, price_model or model, role, max_retries)


def anthropic_client(model: str, temperature: float = 0.7, max_retries: int = 8, role: str = "lab",
                     max_tokens: int = 1024) -> LLM:
    base = _check_url(os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/"))

    def post(messages: list[dict]) -> tuple[str, int, int]:
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        body: dict = {"model": model, "max_tokens": max_tokens, "temperature": temperature,
                      "messages": [m for m in messages if m["role"] != "system"]}
        if system:
            body["system"] = system
        out = _post_json(f"{base}/v1/messages", body, {"x-api-key": key, "anthropic-version": "2023-06-01"})
        text = "".join(b.get("text", "") for b in out.get("content", []) if b.get("type") == "text")
        u = out.get("usage") or {}
        return text, u.get("input_tokens", 0), u.get("output_tokens", 0)

    return _client(post, model, role, max_retries)


def python_client(entrypoint: str) -> LLM:
    module_name, attr = entrypoint.split(":", 1)
    func = getattr(importlib.import_module(module_name), attr)

    async def call(messages: list[dict]) -> str:
        if inspect.iscoroutinefunction(func):
            return await func(messages)
        return func(messages)

    return call


def build_llm(spec: str | None, temperature: float = 0.7, role: str = "lab") -> LLM | None:
    if not spec:
        return None
    if spec == "openai":
        return openai_client(temperature=temperature, role=role)
    if spec.startswith("python:"):
        return python_client(spec.removeprefix("python:"))
    provider, _, model = spec.partition(":")
    if not model:
        raise ValueError(f"LLM spec {spec!r} needs a model, e.g. '{provider}:MODEL'")
    if provider == "anthropic":
        return anthropic_client(model, temperature=temperature, role=role)
    if provider == "ollama":
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        return openai_client(f"{host}/v1", model, "", temperature, role=role, price_model=f"ollama/{model}")
    if provider in OPENAI_COMPATIBLE:
        base, key_var = OPENAI_COMPATIBLE[provider]
        return openai_client(base, model, os.environ.get(key_var, ""), temperature, role=role)
    raise ValueError(f"unknown LLM spec {spec!r}; providers: {', '.join(PROVIDERS)}, openai, python:module:fn")
