# Agent Reliability Lab

Chaos engineering for AI agents. Point it at your agent, attack it with simulated users, prompt
injections, broken tools and poisoned documents, score reliability and safety with confidence intervals,
and block the deploy when a new version gets significantly worse.

```bash
pip install agent-reliability-lab
arl init
arl run --target arl/target.yaml --suite builtin:safety,arl/scenarios
```

## What it catches

| Failure | How |
|---|---|
| Secret or system-prompt leaks | Canary strings in `secrets:`, checked in every reply |
| Jailbreaks and prompt injection | 68 built-in attacks, plus a red-team generator that disguises the ones you block |
| Fragile tool use | Injected errors, timeouts, rate limits, bad or partial data, schema drift |
| Hallucination | Rubric LLM judges, run only after cheap checks pass |
| Runaway loops and cost | Tool-call budgets, token and cost accounting per run |
| Silent regressions | Fisher exact and Mann-Whitney tests between versions; the CI gate fails the PR |

## How it fits

- **CLI and Python package** for local runs.
- **GitHub Action** (or JUnit XML for any CI) to gate pull requests.
- **MCP server** (`arl mcp`) so Claude, Cursor or VS Code can run suites and explain failures.
- **Plugins** for your own checks, attacks, judge rubrics and adapters.

Works with any agent you can call: Python functions, HTTP/OpenAI-compatible endpoints, LangGraph graphs,
MCP servers. Lab models (simulated users, judges) run on OpenAI, Anthropic, Gemini, Groq, OpenRouter or a
local Ollama model.
