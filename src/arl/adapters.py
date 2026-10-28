"""Adapters turn a Target into a uniform async callable (F1).

Agent contract: given the conversation so far (list of {"role", "content"}),
return the assistant reply as a string.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import sys
import urllib.request
from pathlib import Path
from typing import Awaitable, Callable

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
    if not target.url:
        raise ValueError("http adapter needs url")

    def post(messages: list[dict]) -> str:
        req = urllib.request.Request(
            target.url,
            data=json.dumps({"messages": messages}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=target.timeout_s) as resp:
            body = json.loads(resp.read())
        # Accept OpenAI-style or a plain {"content": ...} body.
        if "choices" in body:
            return body["choices"][0]["message"]["content"]
        return body["content"]

    async def call(messages: list[dict]) -> str:
        return await asyncio.to_thread(post, messages)

    return call


def _load(entrypoint: str | None, kind: str):
    if not entrypoint or ":" not in entrypoint:
        raise ValueError(f"{kind} adapter needs entrypoint 'module:attribute'")
    module_name, attr = entrypoint.split(":", 1)
    return getattr(importlib.import_module(module_name), attr)


def _langgraph_adapter(target: Target) -> Agent:
    """A compiled LangGraph graph whose state has a `messages` key (MessagesState)."""
    graph = _load(target.entrypoint, "langgraph")

    async def call(messages: list[dict]) -> str:
        state = await graph.ainvoke({"messages": messages})
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
    return ADAPTERS[target.adapter](target)
