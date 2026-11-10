# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/).

## Unreleased

## 0.2.0

### Added
- Apache-2.0 license, contributing guide, security policy, issue templates.
- Native LLM providers: `openai:`, `anthropic:`, `gemini:`, `groq:`, `openrouter:`, `ollama:` specs.
- Token and cost accounting per run and per role (agent, user, judge, generator); target `prices`, `ARL_PRICES_FILE`.
- `arl init` scaffolds a target, a starter scenario and a CI workflow; `arl suites` lists built-in packs.
- Built-in scenario packs ship in the wheel: `--suite builtin:safety`, comma-separated suites.
- Plugin system: `@arl.check`, `@arl.mutator`, `@arl.adapter`, `arl.register_rubric`; loaded from the `arl.plugins` entry point, `ARL_PLUGINS` or `--plugin`. `criteria.extra` carries plugin settings.
- `arl run --junit-out` writes JUnit XML for any CI system, with target secrets redacted.
- `arl mcp`: the lab as an MCP server (run_suite, run_failures, compare_runs, list_runs, list_suites, init_project).
- Docs site (MkDocs), release workflow (PyPI trusted publishing, GHCR image, GitHub release), wheel install check in CI.
- `arl --version`.
- `ARL_LLM_RPM` pacing for free-tier rate limits; judge outages leave a run unjudged instead of aborting it.

## 0.1.0

### Added
- Runner with Python, HTTP, LangGraph and MCP adapters; OpenTelemetry traces; cassette record and replay.
- 117-scenario library across 7 categories; LLM simulated users.
- Fault injection through `@arl.tool`.
- Deterministic checks, rubric LLM judges, Wilson and bootstrap CIs, Fisher and Mann-Whitney comparisons.
- Red-team generator with 7 mutators.
- HTML report, dashboard, composite GitHub Action, Dockerfile.
