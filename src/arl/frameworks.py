"""Adapters for agent frameworks, so a target can point straight at the framework's agent object.

    adapter: openai_agents   entrypoint: app.agents:support_agent     # agents.Agent (OpenAI Agents SDK)
    adapter: pydantic_ai     entrypoint: app.bot:agent                # pydantic_ai.Agent
    adapter: langchain       entrypoint: app.chain:agent              # any Runnable (create_agent, LCEL chains)
    adapter: crewai          entrypoint: app.crew:crew                # crewai.Crew
    adapter: llamaindex      entrypoint: app.rag:chat_engine          # chat engine or agent

Each framework is imported only when its adapter is used. Agents run in-process, so tools decorated
with `@arl.tool` are observable and fault-injectable exactly as with the python adapter.
"""

from __future__ import annotations

import asyncio
import inspect

from .adapters import ADAPTERS, Agent, _load
from .models import Target


def _transcript_text(messages: list[dict]) -> str:
    """Earlier turns as plain text, for frameworks that take a single input string."""
    return "\n".join(f"{m['role']}: {m['content']}" for m in messages[:-1])


def _with_history(messages: list[dict]) -> str:
    last = messages[-1]["content"]
    history = _transcript_text(messages)
    return f"Conversation so far:\n{history}\n\nuser: {last}" if history else last


async def _maybe_await(value):
    return await value if inspect.isawaitable(value) else value


def _openai_agents(target: Target) -> Agent:
    agent = _load(target.entrypoint, "openai_agents")
    from agents import Runner

    async def call(messages: list[dict]) -> str:
        result = await Runner.run(agent, input=[{"role": m["role"], "content": m["content"]} for m in messages])
        return str(result.final_output)

    return call


def _pydantic_ai(target: Target) -> Agent:
    agent = _load(target.entrypoint, "pydantic_ai")
    from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

    async def call(messages: list[dict]) -> str:
        history = [ModelRequest(parts=[UserPromptPart(content=m["content"])]) if m["role"] == "user"
                   else ModelResponse(parts=[TextPart(content=m["content"])]) for m in messages[:-1]]
        result = await agent.run(messages[-1]["content"], message_history=history or None)
        return str(result.output)

    return call


def _langchain(target: Target) -> Agent:
    runnable = _load(target.entrypoint, "langchain")

    async def call(messages: list[dict]) -> str:
        try:
            out = await runnable.ainvoke({"messages": [(m["role"], m["content"]) for m in messages]})
        except (KeyError, TypeError, ValueError):
            # Chains that take a single input instead of a message list.
            out = await runnable.ainvoke({"input": _with_history(messages)})
        if isinstance(out, dict):
            if "messages" in out:
                out = out["messages"][-1]
            else:
                out = out.get("output", out.get("answer", out))
        return str(getattr(out, "content", out))

    return call


def _crewai(target: Target) -> Agent:
    crew = _load(target.entrypoint, "crewai")

    async def call(messages: list[dict]) -> str:
        inputs = {"input": messages[-1]["content"], "history": _transcript_text(messages)}
        kickoff = getattr(crew, "kickoff_async", None)
        result = await kickoff(inputs=inputs) if kickoff else await asyncio.to_thread(crew.kickoff, inputs=inputs)
        return str(getattr(result, "raw", result))

    return call


def _llamaindex(target: Target) -> Agent:
    engine = _load(target.entrypoint, "llamaindex")

    async def call(messages: list[dict]) -> str:
        if hasattr(engine, "achat"):  # chat engines and legacy agents
            out = await engine.achat(_with_history(messages))
        elif hasattr(engine, "run"):  # workflow agents (FunctionAgent, ReActAgent, AgentWorkflow)
            out = await _maybe_await(engine.run(user_msg=_with_history(messages)))
        else:
            out = await engine.aquery(_with_history(messages))
        return str(getattr(out, "response", out))

    return call


FRAMEWORK_ADAPTERS = {
    "openai_agents": _openai_agents,
    "pydantic_ai": _pydantic_ai,
    "langchain": _langchain,
    "crewai": _crewai,
    "llamaindex": _llamaindex,
}
ADAPTERS.update(FRAMEWORK_ADAPTERS)
