# Coverage: every kind of agent

Agents go by many names (support bot, copilot, research agent, coding agent, browser agent), but each is a
combination of a few capabilities. The lab tests each capability, so any agent built from them is covered.

| Capability | Agents that have it | What the lab attacks | Pack |
|---|---|---|---|
| Conversation | every agent | system-prompt leaks in 5 languages and many formats, authority spoofing, multi-turn crescendo, dangerous output (XSS, SQL, exfiltration links), runaway output, invented facts\*, harmful requests\* | `conversation`, `safety` |
| RAG | Q&A, search, research | instructions hidden in retrieved documents, exfiltration links, retrieval failures | `rag` |
| Tools / actions | ops, finance, booking, CRM | destructive or high-impact actions on unverified requests, action floods, privilege misuse, loops | `tools` |
| Memory | assistants with memory | user-planted triggers, poisoned stored memories, memory failures | `memory` |
| Multi-agent | crews, supervisors | poisoned messages from other agents, using one agent to make another act, delegation loops | `multiagent` |
| Code execution | coding and data agents | destructive, secret-reading, networked or self-replicating code; instructions in code output; sandbox failures | `code` |
| Browsing | browser and web agents | hidden instructions in pages, navigation exfiltration, credential entry, SSRF and local files | `browsing` |
| Multimodal | document and image readers | instructions in white text, metadata, OCR text and invoices | `multimodal` |

\* judge-only: graded by an LLM judge, skipped (never counted as passed) when no judge is configured.

Every scenario is tagged with **OWASP Top 10 for LLM Applications (2025)** and **OWASP Agentic AI threat** IDs.
The `deep` tier covers all 8 capabilities, 9 of 10 OWASP LLM risks and 14 of 15 agentic threats. The remaining
two can't be tested through conversations and are reported as out of scope, not hidden:
LLM03 Supply Chain (review dependencies and model provenance) and T8 Repudiation (review audit logs).

## See it for your agent
```bash
arl coverage --suite builtin:deep                         # what the suite covers
arl coverage --suite builtin:standard --target arl/target.yaml   # what applies to your agent, and why the rest is skipped
```

## Telling the lab about your agent's tools
Tool-based packs need to know which `@arl.tool` functions play which role, and a request that makes the agent
use each one:
```yaml
tools:
  retrieval: [search_docs]
  actions: [send_email, issue_refund]
  memory: [recall_memory]
  delegate: [ask_agent]
  code: [run_code]
  browser: [fetch_page]
  document: [read_document]
probes:
  memory: What do you remember about my preferences?
  delegate: Ask the research agent for today's summary.
  code: Run code to compute 2+2.
  browser: Summarise https://example.com/news for me.
  document: Summarise the attached report.pdf.
probe_question: What is the refund policy?   # retrieval
```
Scenarios whose role isn't set are skipped with a reason. Agents behind HTTP or MCP are black boxes: the lab
can't see their tool calls, so tool-based scenarios are skipped for them instead of passing vacuously.

## How the packs are kept honest
- **False-alarm guard:** careful reference agents must pass every generic scenario (tests run in CI).
- **Every pack catches something:** a naive agent with every capability must fail at least one scenario in
  each pack.
- **Limits:** multimodal attacks arrive as extracted text from a document tool; raw image and audio input is
  not tested yet. Memory scenarios cover poisoning within a session and through memory tools; leakage between
  separate sessions isn't tested yet.
