# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/).

## Unreleased

### Added
- Apache-2.0 license, contributing guide, security policy, issue templates.
- Native LLM providers: `openai:`, `anthropic:`, `gemini:`, `groq:`, `openrouter:`, `ollama:` specs.
- Token and cost accounting per run and per role (agent, user, judge, generator); target `prices`, `ARL_PRICES_FILE`.
- `ARL_LLM_RPM` pacing for free-tier rate limits; judge outages leave a run unjudged instead of aborting it.

## 0.1.0

### Added
- Runner with Python, HTTP, LangGraph and MCP adapters; OpenTelemetry traces; cassette record and replay.
- 117-scenario library across 7 categories; LLM simulated users.
- Fault injection through `@arl.tool`.
- Deterministic checks, rubric LLM judges, Wilson and bootstrap CIs, Fisher and Mann-Whitney comparisons.
- Red-team generator with 7 mutators.
- HTML report, dashboard, composite GitHub Action, Dockerfile.
