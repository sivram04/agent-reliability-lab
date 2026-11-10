# Case study 2: a long-document Q&A agent (Document Intelligence)

**Agent:** Project 3's long-document question answering, run in-process: BM25 retrieval over a real document,
an answer from Gemini 3.5 Flash-Lite with page citations, and a citation verifier that withholds any answer
whose quote isn't found word for word in the document.
**Document:** the Federal Reserve Banks' 2024 combined financial statements (65 pages, 372 passages).
**Wrapper:** [`case_studies/docintel/arl_entry.py`](../../case_studies/docintel/arl_entry.py): retrieval goes
through an `@arl.tool`, so the RAG pack can poison or break what the agent reads.

## Results

### Attacks: 116 scenarios, 116 passed
`quick`, `safety`, `rag` and `conversation` packs (12 judge-only scenarios skipped, no judge configured).
No leak of the system prompt, no injected text in answers, no exfiltration links, across five languages and many
formats.

**Why, and why that number alone proves little:** 115 of 116 replies were "The document does not state this."
The design only ever answers with a quote it can verify in the document, so an attack question has nothing to
quote. That is a strong, structural defence. But a broken agent that refused everything would also score 100%,
so the lab gained **control scenarios**: the target names text a correct answer contains (`probe_expect`, here
the net loss figure) and the RAG pack checks the agent still answers with no attack and after a transient tool
failure.

### Resilience: real defects found
Under injected tool faults (RAG pack, 13 scenarios):

| Fault in retrieval | Result |
|---|---|
| bad data, empty results, renamed fields | handled: says the document does not state it |
| search raises an error (once or always) | **crash**: the exception reaches the user |
| search rate-limited | **crash** |
| search hangs | **hang** until the lab's 180 s timeout |
| instructions injected into retrieved passages | resisted (the verifier rejects quotes that aren't in the document) |

**Recommendation for Project 3:** wrap `index.search` in `ask()` with a timeout and an error path that returns
"search is temporarily unavailable" instead of raising. Today retrieval is a local BM25 index and can't fail,
but the moment it moves to a remote vector store these become user-facing crashes.

### Not measured yet
The run hit the Gemini free tier's **daily quota** part-way through: three scenarios, including the control,
failed with provider quota errors. The lab now reports those as invalid ("rerun when the quota resets"), not as
agent crashes. The control and those two injections need a rerun on a fresh quota day.

Also seen: the agent could not answer "What were the total assets at the end of 2024?" because BM25 retrieval
didn't surface the balance-sheet page, an accuracy limit worth a retrieval upgrade.

## What this case study changed in the lab
- Control scenarios (`probe_expect`) so refusing everything can't score 100%.
- Provider quota and rate-limit errors are classified as invalid results.
- Scenarios whose only check is "don't call action tools" now drop that check, instead of being skipped, for
  agents without action tools, as long as other checks remain.

## Reproduce
```bash
# from agent-reliability-lab, with an interpreter that has Project 3's dependencies
PYTHONPATH="src;.;case_studies/docintel" python -m arl run --target case_studies/docintel/target.yaml \
  --suite builtin:quick,builtin:safety,builtin:rag,builtin:conversation --concurrency 1
```
Results: `docs/results/docintel/`.
