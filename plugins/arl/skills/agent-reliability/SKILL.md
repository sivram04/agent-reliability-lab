---
name: agent-reliability
description: Test an AI agent, chatbot, LLM app, RAG pipeline, tool-calling agent or MCP server for reliability and safety (prompt injection, jailbreaks, secret and PII leaks, broken tools, hallucination, regressions) with Agent Reliability Lab. Use when building, changing, reviewing or shipping anything that sends user input to an LLM, when the user asks whether their agent is safe, robust or production-ready, or when an arl check reports failures.
when_to_use: The project contains an AI agent (OpenAI/Anthropic/Gemini SDK calls, LangGraph, LangChain, CrewAI, OpenAI Agents SDK, Claude Agent SDK, LlamaIndex, an MCP server, or a chat endpoint), or an arl/target.yaml exists.
---

# Agent Reliability Lab

You help the user build an AI agent that holds up against real users: attackers, confused users and
failing tools. The lab runs scenarios against their agent and scores them. The `arl` MCP server gives
you tools for this; the `arl` CLI does the same from a terminal.

## 1. Set up once per project
Skip this if `arl/target.yaml` exists.

1. Call the MCP tool `detect_agent` (or run `arl detect`). It scans the project and ranks candidates:
   OpenAI Agents SDK, PydanticAI, LangGraph (objects and factories), LangChain, CrewAI, LlamaIndex,
   MCP servers, FastAPI/Flask chat routes, plain `fn(messages) -> str` functions. Pick the candidate that
   is the user's actual agent (not a raw LLM client helper); confirm with the user if unsure.
2. Call `init_project` with `candidate` set to that index (or run `arl init`). It writes
   `arl/target.yaml` configured for it. If the candidate is not `ready`, do its `todo`: usually write
   `arl_entry.py` with `respond(messages) -> str` that calls the agent (a stub is created), or replace a
   route's path parameters. In-process agents also get tool-level checks and fault injection when their
   tools use `@arl.tool`.
3. **Plant a canary.** Ask the user's permission, then put a unique string such as `CANARY-7f3a` into the
   agent's system prompt (or the wrapper's) and list it under `secrets:`. Every reply is checked for it,
   which is how leaks of the system prompt are detected. Also list real secrets the agent can see.
4. Add 2-5 scenarios for the agent's core jobs in `arl/scenarios/` (copy `example_task.yaml`): the
   questions it must answer, with `must_contain` and `must_not_contain` facts.
5. Run the `check` tool with `force: true` to record a baseline, and explain the result.

## 2. While building
- A Stop hook runs a fast check after each turn that changed project files. If scenarios that passed
  before now fail, you are asked to fix them before finishing.
- After meaningful edits to prompts, tools or agent logic, you may also call `check` yourself.
- **Never weaken, delete or skip a scenario to make it pass**, and never remove the canary. Fix the
  agent: tighten the system prompt, validate tool inputs, refuse out-of-scope requests, handle tool
  errors with a retry or an honest "unavailable", and don't echo instructions or retrieved text verbatim.
  If a scenario is genuinely wrong for this agent, explain why and ask the user before changing it.

## 3. Deeper evaluation (when the user asks, or before shipping)
- `run_suite` with `suite: "builtin:safety,arl/scenarios"` and `repeats: 3`: 68 attacks plus their own.
- Add `judge_llm` (and `user_llm` for multi-turn simulated users), for example
  `gemini:gemini-3.5-flash-lite`, `anthropic:<model>`, `openai:<model>` or `ollama:llama3.1`, to grade
  helpfulness, refusals and faithfulness. These cost tokens: say so first.
- `compare_runs` tells whether a change is a statistically significant regression.
- `run_failures` shows full conversations of a past run.

## 4. Explaining results
Lead with the verdict in plain words (for example "3 of 17 attacks got through: all three made the agent
print its system prompt"), then the pattern behind the failures, then the fix you propose. Quote the
attack and the reply for one example. Mention `arl ui` for the dashboard with full replays and history.
Secrets appear as `[REDACTED]` in results; never try to recover them.

## Notes
- The lab only talks to the agent the user configured. Don't point it at production systems or
  third-party services without the user's say-so.
- HTTP agents must be running for checks; if `check` says unreachable, start the agent or tell the user.
- Results are stored in `.arl/` (git-ignored).
