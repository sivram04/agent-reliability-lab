# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/).

## Unreleased

### Added
- Claude Code plugin (`plugins/arl`, marketplace in `.claude-plugin/`): `agent-reliability` skill, Stop hook, MCP server.
- `arl check`: fast, change-aware check that reports only new failures and fixes; `--hook stop` for Claude Code.
- `builtin:quick`: 16 generic attacks that work on any agent through its `secrets:` canary.
- MCP tool `check`; `python -m arl`; runs record their source (cli, check, mcp).
- `arl detect` and `arl init` (auto by default): static scan finds the agent and configures the target; ranks
  candidates, flags raw LLM helpers, routes with path parameters and graphs that need a wrapper (writes an
  `arl_entry.py` stub). MCP tool `detect_agent`.
- Framework adapters: `openai_agents`, `pydantic_ai`, `langchain`, `crewai`, `llamaindex`.
- LangGraph adapter accepts zero-argument factories and graphs compiled with a checkpointer.
- `builtin:rag` (12) and `builtin:tools` (7) packs, bound to the target's `tools` roles and `probe_question`;
  scenarios that can't apply are skipped with a reason instead of passing vacuously.

- Flakiness: per-scenario outcomes across repeats (always pass / always fail / flaky); `arl check` re-runs new
  failures and only blocks on ones that fail every time.
- Plain-English findings (`arl.explain`): failures grouped by problem and attack technique, with an example and
  a fix, in `arl run`, `arl check`, the hook and MCP. `arl run --verbose` lists every failing run.
- False-alarm guard: careful reference agents must pass every generic scenario (CI test).
- Tiers `builtin:quick`, `builtin:standard`, `builtin:deep`; unique per-project canaries from `arl init`; `arl canary`.

- Judge agreement study (`docs/judge-agreement.md`): stricter `refusal` rubric for soft leaks (kappa 0.50 -> 0.73
  vs. an AI annotator, in-sample); `scripts/rejudge.py` re-scores saved conversations, resumable.

- Coverage of every kind of agent: capability packs `conversation` (45), `memory` (10), `multiagent` (8), `code` (11),
  `browsing` (9), `multimodal` (7); tiers `standard` (179) and `deep` (228). Every scenario tagged with capability,
  OWASP LLM Top 10 2025 and OWASP agentic threat IDs (`arl.taxonomy`); `arl coverage` reports coverage and skip
  reasons per target.
- Checks `forbid_patterns`, `forbid_tool_args`, `max_reply_chars`; `judge_only` scenarios (skipped without a judge);
  `honesty` and `safety` rubrics; generic tool roles (`$role`, `probes`).

- `arl generate`: attacks specific to an agent from its profile (extracted by an LLM from the system prompt, or
  written by hand for offline use): templates plus LLM-written attacks per OWASP risk, validated, deduplicated
  (also across runs), tagged, honestly graded (judge-only where the canary can't decide); secret values are
  scrubbed from prompts and files. MCP tool `generate_attacks`.

### Fixed
- LLM calls retry dropped connections and timeouts, not only 429/5xx.
- Smoke attack scenarios now use the target's `secrets:` instead of only the fixture's code.
- Scenarios tied to tools a target doesn't declare are skipped instead of failing; one safety scenario no longer
  requires an order-bot fact.

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
