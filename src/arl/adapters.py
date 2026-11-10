"""Adapters turn a Target into a uniform async callable (F1).

Agent contract: given the conversation so far (list of {"role", "content"}),
return the assistant reply as a string.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import os
import random
import sys
import urllib.error
import urllib.request
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

from . import usage
from .models import Target

Agent = Callable[[list[dict]], Awaitable[str]]


def _python_adapter(target: Target) -> Agent:
    func = _load(target.entrypoint, "python")

    async def call(messages: list[dict]) -> str:
        if inspect.iscoroutinefunction(func):
            return await func(messages)
        return await asyncio.to_thread(func, messages)

    return call


def _http_adapter(target: Target) -> Agent:
    """POST {"messages": [...]} (plus "model" and a system prompt when the target sets them,
    i.e. an OpenAI-compatible chat endpoint). Error responses whose type is in
    `target.block_types` are refusals by the target's own guardrails and become the reply
    "[blocked: ...]"; transient upstream errors are retried with backoff."""
    if not target.url:
        raise ValueError("http adapter needs url")
    headers = {"Content-Type": "application/json",
               **{k: os.path.expandvars(v) for k, v in target.headers.items()}}

    def post(messages: list[dict]) -> str:
        payload: dict = {"messages": messages}
        if target.system_prompt:
            payload["messages"] = [{"role": "system", "content": target.system_prompt}, *messages]
        if target.model:
            payload["model"] = target.model
        req = urllib.request.Request(  # nosec B310 - Target validates the url scheme (http/https only)
            target.url, data=json.dumps(payload).encode(), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=target.timeout_s) as resp:  # nosec B310 - validated scheme
                body = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            try:
                err = json.loads(exc.read()).get("error", {})
            except (ValueError, AttributeError):
                err = {}
            if isinstance(err, dict) and err.get("type") in target.block_types:
                return f"[blocked: {err.get('type')}: {err.get('message', '')}]"
            raise
        # Accept OpenAI-style or a plain {"content": ...} body.
        if "choices" in body:
            u = body.get("usage") or {}
            if u:
                usage.record("agent", body.get("model") or target.model,
                             u.get("prompt_tokens", 0), u.get("completion_tokens", 0))
            return body["choices"][0]["message"]["content"] or ""
        return body["content"]

    async def call(messages: list[dict]) -> str:
        for attempt in range(target.max_retries + 1):
            try:
                return await asyncio.to_thread(post, messages)
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 500, 502, 503) or attempt == target.max_retries:
                    raise
                await asyncio.sleep(min(60, 2 ** (attempt + 1)) + random.random())
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                # A dropped connection is a network blip, not the agent crashing: retry before failing.
                if attempt == target.max_retries:
                    raise
                await asyncio.sleep(min(30, 2 ** attempt) + random.random())
        raise RuntimeError("unreachable")

    return call


def _load(entrypoint: str | None, kind: str):
    if not entrypoint or ":" not in entrypoint:
        raise ValueError(f"{kind} adapter needs entrypoint 'module:attribute'")
    module_name, attr = entrypoint.split(":", 1)
    return getattr(importlib.import_module(module_name), attr)


def _langgraph_adapter(target: Target) -> Agent:
    """A compiled LangGraph graph whose state has a `messages` key (MessagesState), or a function
    with no arguments that builds one."""
    graph = _load(target.entrypoint, "langgraph")
    if not hasattr(graph, "ainvoke") and callable(graph):
        graph = graph()

    async def call(messages: list[dict]) -> str:
        # A fresh thread per call: graphs compiled with a checkpointer require one, and the lab already
        # sends the whole conversation, so state must not accumulate across calls.
        config = {"configurable": {"thread_id": uuid.uuid4().hex}}
        state = await graph.ainvoke({"messages": messages}, config=config)
        last = state["messages"][-1]
        return last.content if hasattr(last, "content") else last["content"]

    return call


def _mcp_adapter(target: Target) -> Agent:
    """An MCP server over stdio. One server process per call keeps runs isolated."""
    if not target.command:
        raise ValueError("mcp adapter needs command")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    argv = [sys.executable if a == "{python}" else a for a in target.command]
    params = StdioServerParameters(command=argv[0], args=argv[1:], cwd=str(Path.cwd()))

    async def call(messages: list[dict]) -> str:
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                target.tool, {"messages": messages}, read_timeout_seconds=target.timeout_s
            )
        text = "".join(getattr(c, "text", "") for c in result.content)
        if result.is_error:
            raise RuntimeError(f"MCP tool error: {text}")
        return text

    return call


ADAPTERS = {
    "python": _python_adapter,
    "http": _http_adapter,
    "langgraph": _langgraph_adapter,
    "mcp": _mcp_adapter,
}


def build_agent(target: Target) -> Agent:
    from . import frameworks  # noqa: F401  registers the framework adapters

    if target.adapter not in ADAPTERS:
        raise ValueError(f"unknown adapter {target.adapter!r}; available: {', '.join(sorted(ADAPTERS))} "
                         "(plugins can add more)")
    return ADAPTERS[target.adapter](target)
