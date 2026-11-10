# Agent Reliability Lab

**Attack your AI agent before your users do, and catch it getting worse while you build it.**

[![ci](https://github.com/sivram04/agent-reliability-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/sivram04/agent-reliability-lab/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

Agent Reliability Lab is an open-source testing lab for AI agents: chatbots, RAG pipelines, tool-calling,
coding, browsing and multi-agent systems. It attacks your agent with prompt injections, jailbreaks and
secret-extraction attempts. It breaks its tools on purpose and poisons its documents, then tells you in plain
words what failed, shows the exact conversation and suggests the fix. It measures with confidence intervals and
blocks a release when a new version is significantly worse.

It works where you build agents. In **Claude Code** a plugin checks your agent in the background after every
change and makes Claude fix what broke. Through **MCP**, Claude Desktop, Cursor and VS Code can run it. In **CI**
it gates pull requests. A local **dashboard** shows every run as an investigation file.

> Runs locally and offline. LLM judges and simulated users are optional and work with free tiers
> (Gemini, Groq) or a local Ollama model. Your agent's secrets are redacted from everything the lab stores.

![Agent Reliability Lab dashboard: a run with 8 problems found, the attack, the agent's reply with the leaked secret marked, and the fix](docs/img/run.jpg)

---

## Contents
1. [Why it exists](#1-why-it-exists)
2. [What it does](#2-what-it-does)
3. [Results](#3-results)
4. [Architecture](#4-architecture)
5. [Stack, and why](#5-stack-and-why)
6. [How it works](#6-how-it-works)
7. [Trust: how results are kept honest](#7-trust-how-results-are-kept-honest)
8. [Use it with Claude (plugin and MCP)](#8-use-it-with-claude-plugin-and-mcp)
9. [CI/CD](#9-cicd)
10. [Run it locally](#10-run-it-locally)
11. [Testing](#11-testing)
12. [Repository layout](#12-repository-layout)
13. [Limits, stated plainly](#13-limits-stated-plainly)
14. [License and privacy](#14-license-and-privacy)

Step-by-step instructions for every feature are in the **[user guide](docs/USER_GUIDE.md)**.

---

## 1. Why it exists

A one-line prompt change or a model swap can quietly make an agent print its system prompt, obey instructions
hidden in a web page, or give up the moment a tool times out. Unit tests don't catch it, a few manual chats prove
nothing, and agents are random, so one run can mislead either way.

The lab is built around four rules:

| Rule | What it means in the product |
|---|---|
| **Attack by capability** | Any agent is a mix of 8 capabilities (conversation, RAG, tools, memory, multi-agent, code, browsing, multimodal). Each has its own attack pack, mapped to OWASP risks |
| **Statistics, not anecdotes** | Pass rates carry 95% intervals, flaky scenarios are re-run before anyone is blamed, and version comparisons use significance tests |
| **A skip is never a pass** | Anything the lab can't check for your agent (no judge, no tool visibility, missing setup) is skipped with the reason, never counted as passed |
| **Explain, then prove** | Failures are grouped into a few problems in plain English, each with the exact attack, the reply and a fix |

## 2. What it does

| Area | What you get |
|---|---|
| **Attacks** | 229 scenarios: jailbreaks and prompt injection in 5 languages and many formats, authority spoofing, multi-turn manipulation, PII extraction, dangerous output (XSS, SQL, exfiltration links), runaway output, harmful requests |
| **Every kind of agent** | Packs for RAG (poisoned documents), tools (unauthorised actions), memory (poisoned memories), multi-agent (forged agent messages), code execution (destructive code), browsing (malicious pages, SSRF) and multimodal (hidden text in documents) |
| **Your agent's own attacks** | `arl generate` reads your system prompt, works out what the agent protects and can do, and writes attacks for it |
| **Chaos** | `@arl.tool` lets the lab inject errors, timeouts, rate limits, bad or partial data, schema drift and poisoned facts into your agent's tools |
| **Findings** | "38 of 63 failed across 8 problems": each problem with why it matters, the attack, the reply (leaked secrets marked) and a concrete fix |
| **Gate** | Fisher exact and Mann-Whitney tests between versions; `arl compare` exits 1 on a significant regression |
| **Background checks** | `arl check` runs 16 attacks plus your scenarios in seconds and reports only what changed; the Claude Code hook runs it after every change |
| **Dashboard** | `arl ui`: history with intervals, findings, OWASP and capability coverage, step-by-step replays, comparisons; exports a read-only static site |
| **Integrations** | Claude Code plugin, MCP server, GitHub Action, JUnit XML for any CI, OpenTelemetry traces, plugins for custom checks, attacks and adapters |
| **Frameworks** | Auto-detects and tests OpenAI Agents SDK, PydanticAI, LangGraph, LangChain, CrewAI, LlamaIndex, MCP servers, HTTP endpoints and plain Python functions |

| All agents and their history | What a run covered |
|---|---|
| ![Dockets: every agent with its pass rate over time and every run](docs/img/dashboard.jpg) | ![Coverage: 8 capabilities and OWASP risks, tested or untested](docs/img/coverage.jpg) |

## 3. Results

Every figure below comes from runs and tests in this repository that you can rerun.

| Test | Result | Notes |
|---|---|---|
| Real Gemini support bot, strong vs weak system prompt | **98% vs 40%** of attacks resisted | Same model; the weak prompt leaked its staff discount code backwards, in an acrostic and in base64 ([judge study](docs/judge-agreement.md)) |
| 56 attacks written by `arl generate` for that bot | **55 resisted** | 1 failure was a dropped connection; network errors are now retried |
| Real long-document Q&A agent (Project 3, Fed 2024 report) | **116/116 attacks resisted**; **4 crash or hang defects** | Structurally safe because answers must be verified quotes; tool faults exposed missing error handling ([case study](docs/case-studies/02-docintel.md)) |
| LLM gateway guardrails (Project 1) | **122 bypasses → 0** after hardening | Base64 and leetspeak bypassed the classifier every time; 0 false positives after the fix ([case study](docs/case-studies/01-gateway-guardrails.md)) |
| LLM judge vs reference labels | **kappa 0.50 → 0.73** | After tightening the refusal rubric for soft leaks; reference labels are from an AI annotator, measured in-sample |
| CI gate demo | tool chaos **100% → 67%**, p < 0.001, **blocked** | Removing a retry loop in v2 |
| Fairness | careful agents pass every pack, naive ones are caught in every pack | Enforced in the test suite, so a badly written scenario can't slip in |

## 4. Architecture

```mermaid
flowchart TB
  subgraph Sources["Where it runs"]
    CC["Claude Code plugin<br/>skill + Stop hook"]
    MCP["MCP server<br/>Claude Desktop, Cursor, VS Code"]
    CLI["arl CLI"]
    GHA["GitHub Action / any CI"]
  end
  CC --> CHECK["arl check<br/>fast, change-aware"]
  MCP --> RUN
  CLI --> RUN["arl run"]
  GHA --> RUN
  CHECK --> RUN
  RUN --> BIND["Scenario packs<br/>bound to your agent's tools,<br/>skipped with reasons"]
  BIND --> RUNNER["Runner<br/>repeats, timeouts, simulated users"]
  RUNNER --> ADAPT["Adapters<br/>Python, HTTP, LangGraph, MCP,<br/>OpenAI Agents, PydanticAI, CrewAI, ..."]
  ADAPT --> AGENT(["Your agent"])
  AGENT --> TOOLS["@arl.tool<br/>fault injection"]
  RUNNER --> SCORE["Checks<br/>leaks in every form, tools, output, cost"]
  SCORE --> JUDGE["LLM judges<br/>only if checks pass"]
  JUDGE --> REDACT["Redact secrets"]
  REDACT --> DB[("SQLite results")]
  DB --> EXPLAIN["Findings + statistics"]
  EXPLAIN --> UI["Dashboard / export"]
  EXPLAIN --> GATE["Compare + gate<br/>JUnit, PR comment"]
```

## 5. Stack, and why

| Layer | Choice | Why |
|---|---|---|
| Core | **Python 3.11+**, **Pydantic**, **Typer** | Typed scenario and target files, strict validation (a typo is an error, not a silent pass), one CLI |
| Statistics | **SciPy** (Fisher exact, Mann-Whitney), Wilson and bootstrap intervals | Agents are stochastic; decisions need significance, not a single run |
| Storage | **SQLite** | One file per project, zero setup, indexed for 10,000+ runs |
| LLMs (optional) | Any OpenAI-compatible API, Anthropic, **Gemini**, **Groq**, OpenRouter, **Ollama** | Judges and simulated users on free tiers or fully local |
| Agent frameworks | LangGraph, OpenAI Agents SDK, PydanticAI, LangChain, CrewAI, LlamaIndex, MCP | Point the lab at the framework's agent object; nothing to wrap |
| Claude integration | **Claude Code plugin**, **MCP** (Python SDK) | Testing happens inside the tool developers already use |
| Dashboard | One static app, no build step, bundled D-DIN font | Works offline, exports as a self-contained site, nothing to install |
| CI | **GitHub Actions**, JUnit XML | Gate pull requests on GitHub or any CI that reads JUnit |
| Quality | **pytest** + **Hypothesis**, **ruff**, **bandit**, **pip-audit** | 210 tests, 94% coverage, fuzzing, security scans on every push |

## 6. How it works

**In Claude Code, while you build**

```mermaid
sequenceDiagram
  participant D as You
  participant C as Claude Code
  participant H as Stop hook (arl check)
  participant A as Your agent
  D->>C: "Add a refund tool to the support agent"
  C->>C: edits the agent
  C->>H: turn ends
  H->>H: files changed? (fingerprint)
  H->>A: 16 attacks + your scenarios
  A-->>H: replies, tool calls
  H->>H: new failures? re-run twice to rule out flakiness
  H-->>C: "2 scenarios that passed now fail: the refund tool leaks the system prompt. Fix: ..."
  C->>C: fixes the agent, re-checks
  C-->>D: done, all scenarios pass
```

**One run, step by step**
1. **Bind.** Scenario packs are matched to your agent: tool roles (`retrieval`, `actions`, `memory`, ...) map to
   your functions; anything that can't apply is skipped with the reason.
2. **Run.** Each scenario's turns go to your agent, with a simulated user for multi-turn goals. Injected faults
   hit your tools. Every call has a timeout; a crash fails one scenario, never the run.
3. **Check.** Deterministic checks first: secret leaks in any form (verbatim, reversed, spaced out,
   re-punctuated, base64, hex), forbidden tools and arguments, dangerous output, loops, latency, cost.
4. **Judge.** Only runs that pass the checks go to the LLM judge (refusal, helpfulness, faithfulness, honesty,
   safety), which keeps judge cost low.
5. **Explain and gate.** Failures become plain-English findings; results are compared against a baseline with
   significance tests; secrets are redacted before anything is saved.

## 7. Trust: how results are kept honest

| Risk | How the lab handles it |
|---|---|
| A test that checks nothing passes | Scenarios with no applicable check are skipped with a reason; typos in config files are errors |
| An agent that refuses everything scores 100% | Control scenarios require a correct answer when nothing is under attack (`probe_expect`) |
| Random agents mislead | Repeats, 95% intervals, and new failures re-run before they count as regressions |
| A provider quota looks like an agent bug | Quota and rate-limit errors are reported as invalid results to rerun |
| Scenarios that flag well-behaved agents | Careful reference agents must pass every pack, enforced in CI |
| An unreliable LLM judge | Judges only see runs that passed deterministic checks; agreement is measured ([study](docs/judge-agreement.md)) |
| The lab leaking your secrets | Secrets are redacted in every recognised form before results are saved, printed or published |
| Attack text in published reports | Every report and dashboard view escapes content; the dashboard refuses foreign Host headers |

Before this release the lab went through three rounds of independent adversarial review and about 25 defects
were found, fixed and re-verified. Each one now has a regression test (`tests/test_review_fixes.py`).

## 8. Use it with Claude (plugin and MCP)

**Claude Code plugin.** Install the lab where your agent's packages live, then add the plugin:
```bash
pip install "agent-reliability-lab[mcp] @ git+https://github.com/sivram04/agent-reliability-lab"
```
```
/plugin marketplace add sivram04/agent-reliability-lab
/plugin install arl@agent-reliability-lab
```
You get a skill (Claude knows how to set up the lab, plant a canary and fix failures without weakening tests),
a Stop hook (the background check after every change) and the MCP tools below.

**MCP server** for Claude Desktop, Cursor, VS Code or any MCP client:
```json
{"mcpServers": {"arl": {"command": "arl", "args": ["mcp"]}}}
```

| Tool | What it does |
|---|---|
| `detect_agent` / `init_project` | find the agent in a project and set up the lab, with a unique canary |
| `check` | fast change-aware check: new failures and fixes since last time |
| `run_suite` | run any pack; returns findings, failures and skipped scenarios |
| `generate_attacks` | write attacks specific to this agent |
| `run_failures`, `compare_runs`, `list_runs`, `list_suites` | dig into results and regressions |

Ask: *"Set up Agent Reliability Lab for this agent, run the standard tier and fix what fails."* See the
[user guide](docs/USER_GUIDE.md#6-use-it-from-claude) for full setup.

## 9. CI/CD

| Workflow | Runs | What it checks |
|---|---|---|
| `ci.yml` | every push and PR | ruff; bandit (medium/high fail); pip-audit; tests on Linux, macOS, Windows with Python 3.11 and 3.13; 90% coverage gate; wheel install and the new-user path; docs build |
| `reliability.yml` | every push and PR | the lab gating its own fixture agents with the GitHub Action |
| `docs.yml` | push to `main` | publishes the documentation site to GitHub Pages |
| `release.yml` | version tag | tests, build, PyPI (trusted publishing), Docker image to GHCR, GitHub release |

Gate your own agent's pull requests:
```yaml
- uses: sivram04/agent-reliability-lab@main
  with:
    target: arl/target.yaml
    suite: builtin:standard,arl/scenarios
    repeats: "3"
    baseline: arl/baseline.json
```

## 10. Run it locally

```bash
pip install "agent-reliability-lab @ git+https://github.com/sivram04/agent-reliability-lab"
cd your-agent-project
arl init        # finds your agent, writes arl/target.yaml with a unique canary
arl check       # 16 attacks in seconds
arl run --target arl/target.yaml --suite builtin:standard --repeats 3
arl ui          # the dashboard
```
Add the canary sentence `arl init` prints to your agent's system prompt; that's how prompt leaks are caught.
Full walkthrough: [user guide](docs/USER_GUIDE.md).

## 11. Testing

```bash
pip install -e ".[dev]"
pytest -q                       # 210 tests, offline, about a minute
ruff check . && bandit -q -r src -ll
```
The suite covers adapters and frameworks (real OpenAI Agents SDK and PydanticAI objects), every pack against
careful and naive agents, fuzzing with Hypothesis (random hook input, random replies), misbehaving agents (hangs,
crashes, wrong types, control characters), corrupt configs and databases, 3,000-run histories, the dashboard API
and export, the MCP server over a real stdio client, and a regression test for every review finding.

## 12. Repository layout

```
src/arl/              the package: runner, adapters, checks, judges, statistics, redaction, CLI
  ui/                 dashboard server and static app
  mcp_server.py       MCP tools
scenarios/            built-in packs (library, quick, rag, tools, conversation, memory, ...)
plugins/arl/          Claude Code plugin: skill, Stop hook, MCP config
.claude-plugin/       plugin marketplace
case_studies/         real agents: LLM gateway, document Q&A, research desk
fixtures/             reference agents (careful and naive) used by the tests
docs/                 documentation site, user guide, case studies, results
tests/                210 tests
action.yml            GitHub Action
```

## 13. Limits, stated plainly

- Leak detection and redaction don't recognise URL or HTML encoding, homoglyphs or base64 that starts
  mid-token. Secrets shorter than 4 characters only match whole words.
- Tool-dependent scenarios need agents that run in-process; HTTP and MCP agents are black boxes, so those
  scenarios are skipped with a reason.
- Multimodal attacks arrive as text from document tools; raw images and audio aren't tested yet. Memory leaks
  between separate sessions aren't tested yet.
- The judge's agreement was measured against an AI annotator, in-sample; a human-labelled study is pending.
- A hung synchronous Python agent is abandoned after its timeout, but its thread can't be killed.
- Interrupting a run loses that run's results; they're saved when the suite finishes.

## 14. License and privacy

Apache 2.0. The lab runs on your machine; nothing is sent anywhere except to the agent you point it at and the
LLM providers you configure for judges or simulated users. Results are stored locally with secrets redacted.
Run attack suites against test environments, not production. See [SECURITY.md](SECURITY.md) and
[CONTRIBUTING.md](CONTRIBUTING.md).
