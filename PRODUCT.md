# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack
No-build static app: plain HTML, CSS and JavaScript shipped inside the Python package and served by `arl ui`
(stdlib HTTP server and a JSON API over the results database). `arl ui --export` writes a self-contained,
read-only copy that opens without the lab installed (attachable, or hostable on GitHub Pages).

## Users
Primary: developers building AI agents (chatbots, RAG, tool-using, coding, browsing, multi-agent), who run the
lab locally and in CI and open the dashboard daily to see what broke and why. Secondary: their teammates and
managers, who receive a shared or exported dashboard to judge whether an agent is safe and improving.

## Product Purpose
Agent Reliability Lab attacks an AI agent with scenarios (prompt injection, jailbreaks, leaks, tool faults,
poisoned data), scores reliability and safety with confidence intervals, and blocks releases that get
significantly worse. The dashboard makes those results understandable: what failed, how the attack worked,
how to fix it, and whether things are getting better over time.

## Positioning
Testing by capability (conversation, RAG, tools, memory, multi-agent, code, browsing, multimodal) mapped to
OWASP LLM Top 10 and OWASP agentic threats; statistics rather than single runs; plain-English findings with
the exact attack and reply; honest reporting of what was skipped and why; runs in the background while the
agent is being built (Claude Code plugin, MCP, `arl check`).

## Operating Context
Runs on a developer laptop next to their editor and in CI. Data comes from SQLite result databases
(`.arl/arl.db` from background checks, `arl.db` from manual runs). Run sources: cli, check, mcp, ci.
Results include transcripts, tool calls with injected faults, judge verdicts and token usage.

## Capabilities and Constraints
- Local, private by default: binds to 127.0.0.1; transcripts may contain attack text and agent replies.
- Must work offline, with no external network requests or CDN dependencies.
- Exported copies are read-only.
- Open source (Apache-2.0).

## Evidence on Hand
Real result databases: fixture agents, the LLM-gateway case study, and a real Gemini support agent
(`docs/results/judge/arl.db`). No user testimonials or adoption numbers exist; none may be invented.

## Product Principles
1. Show the verdict first, then why, then the evidence.
2. Never let a skipped or ungraded test look like a pass.
3. Every failure is one click from the exact conversation that caused it.
4. Plain words over jargon; statistics are shown with their uncertainty.
