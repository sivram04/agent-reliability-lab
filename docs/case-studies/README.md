# Case studies (Phase 7)

| # | Target | Status |
|---|---|---|
| 1 | [LLM gateway guardrails](01-gateway-guardrails.md) (Project 1) | **Done.** Guardrail bypass measured, a fix applied through policy, re-run with before/after numbers. |
| 2 | [Document intelligence Q&A](02-docintel.md) (Project 3) | **Done, one rerun pending.** 116/116 attacks resisted (structurally, via citation verification); 4 real resilience defects (search errors crash, hangs). Control scenario needs a rerun after the Gemini quota reset. |
| 3 | AI research desk (Project 2) | **Blocked on the desk itself.** Wrapper written (`case_studies/research_desk/arl_entry.py`, human-in-the-loop off, filing search as an `@arl.tool`). Loading the desk's local Qdrant index did not finish in 15 minutes on this laptop, and one question takes 8–10 Gemini calls; the desk needs a faster index load before a suite is practical. |

Still open for case study 1:
- **Failover under chaos.** This needs the gateway running with provider keys. The lab's HTTP adapter
  plus `Fault` latency and error modes on a stub provider would cover it.
- **Real-model numbers.** The current study uses a worst-case stub model. Re-running with
  `--user-llm openai --judge-llm openai` through the gateway once keys are set gives real-model
  numbers, plus judge-human agreement after `arl label annotate`.

## How to add a target

1. Write a target YAML: an `http` adapter for a running service, or `python`/`langgraph` for code you can
   import. Wrap the agent's tools with `@arl.tool` so faults can be injected.
2. List the target's secrets (system-prompt canaries, keys) under `secrets:`.
3. Run `arl run --suite scenarios/library`, then `arl redteam`, then fix and re-run with `arl compare`.
