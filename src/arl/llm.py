"""LLM clients for the lab's own models (simulated users, judges, generator).

All of them share the agent call shape: `await llm(messages) -> str`, so the
same cassettes record and replay them.

Spec strings:
    openai                  OpenAI-compatible endpoint from env vars:
                            ARL_LLM_BASE_URL (default: Project 1 gateway at http://localhost:8000/v1),
                            ARL_LLM_MODEL, ARL_LLM_API_KEY. Works with Groq, OpenRouter, Gemini's
                            OpenAI endpoint, or Ollama (http://localhost:11434/v1).
    python:module:function  a local function, sync or async (used for offline fixtures).
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

LLM = Callable[[list[dict]], Awaitable[str]]

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


def openai_client(
    base_url: str | None = None, model: str | None = None, api_key: str | None = None,
    temperature: float = 0.7, max_retries: int = 8,
) -> LLM:
    base = (base_url or os.environ.get("ARL_LLM_BASE_URL", "http://localhost:8000/v1")).rstrip("/")
    model = model or os.environ.get("ARL_LLM_MODEL", "llama-3.1-8b-instant")
    key = api_key or os.environ.get("ARL_LLM_API_KEY", "")

    def post(messages: list[dict]) -> str:
        req = urllib.request.Request(
            f"{base}/chat/completions",
            data=json.dumps({"model": model, "messages": messages, "temperature": temperature}).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())["choices"][0]["message"]["content"]

    async def call(messages: list[dict]) -> str:
        async with _semaphore():
            for attempt in range(max_retries):
                await _pace()
                try:
                    return await asyncio.to_thread(post, messages)
                except urllib.error.HTTPError as exc:
                    if exc.code not in (429, 500, 502, 503) or attempt == max_retries - 1:
                        raise
                    # Per-minute free-tier limits reset within a minute: back off up to 60 s.
                    await asyncio.sleep(min(60, 2 ** (attempt + 1)) + random.random())
        raise RuntimeError("unreachable")

    return call


def python_client(entrypoint: str) -> LLM:
    module_name, attr = entrypoint.split(":", 1)
    func = getattr(importlib.import_module(module_name), attr)

    async def call(messages: list[dict]) -> str:
        if inspect.iscoroutinefunction(func):
            return await func(messages)
        return func(messages)

    return call


def build_llm(spec: str | None, temperature: float = 0.7) -> LLM | None:
    if not spec:
        return None
    if spec == "openai":
        return openai_client(temperature=temperature)
    if spec.startswith("python:"):
        return python_client(spec.removeprefix("python:"))
    raise ValueError(f"unknown LLM spec {spec!r}")
