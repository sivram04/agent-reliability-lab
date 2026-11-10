# How much can you trust the LLM judge?

The lab's judges grade what exact-match checks can't: hints, paraphrases and encoded leaks. A judge is only
useful if its verdicts match careful labels, so this page measures that and reports what changed as a result.

## Data
- **Agent:** a real Gemini 3.5 Flash-Lite support bot ("Acme Outdoor Gear") with two confidential secrets in its
  system prompt, run with a strong system prompt (63 conversations, 98% of attacks resisted) and a weak one
  (30 conversations that reached the judge; 40% of attacks resisted overall).
- **Scenarios:** `builtin:safety` (jailbreaks, prompt injection, secret and PII extraction). Only conversations
  that passed the exact-match checks reach the judge, so these are the hard cases.
- **Judge:** Gemini 3.5 Flash-Lite at temperature 0, `refusal` rubric.
- **Reference labels:** 93 conversations labelled **by an AI annotator (Claude Opus 5.5), not a human**, without
  seeing the judge's verdicts, using written rules ([`labels/annotate.py`](../labels/annotate.py)).
  Two labels were corrected after review because they broke the annotator's own stated rules; both corrections
  are recorded in that file.

## Results

| Judge rubric | Agreement | Cohen's kappa | Judge missed (soft leaks) | Judge too strict |
|---|---|---|---|---|
| Original | 89% | 0.50 | 10 | 0 |
| Revised | **94%** | **0.73** | 6 | 0 |

**What the judge caught that exact matching missed:** the secret spelled backwards, an acrostic poem spelling the
discount code, and the whole system prompt base64-encoded. None of these contain the secret string, so
`no_secret_leak` passed them; the judge failed all three.

**What the original judge missed:** soft leaks. It passed the agent summarising its own instructions when asked
for its system prompt, casually offering the confidential staff discount to strangers, and agreeing to share
other people's data after "verification" with details anyone could know.

**What changed:** the `refusal` rubric now names those patterns explicitly
([`src/arl/judges.py`](../src/arl/judges.py)). Re-scoring the same 93 conversations
([`scripts/rejudge.py`](../scripts/rejudge.py)) raised kappa from 0.50 to 0.73. The remaining misses are mostly
the staff-discount hints (4 of 6).

## Limits, stated plainly
- **Not human labels.** This is agreement between two different model families. It catches judge blind spots,
  but a human-labelled batch is still the gold standard; `labels/batch1.jsonl` is ready for one
  (`arl label annotate labels/batch1.jsonl`).
- **In-sample.** The revised rubric was written after seeing these disagreements, so 0.73 is optimistic until it
  is measured on a fresh batch.
- **One rubric, one domain.** Only `refusal` on a support bot. `helpfulness` and `faithfulness` need their own
  batches.
- **Small and imbalanced.** 93 items, 16 labelled as failures.

## Reproduce
```bash
export GEMINI_API_KEY=...   # free tier is enough
arl run --target case_studies/judge/target_gemini_support.yaml --suite builtin:safety \
  --judge-llm gemini:gemini-3.5-flash-lite --db docs/results/judge/arl.db
arl label export --run RUN_ID --db docs/results/judge/arl.db --out labels/batch1.jsonl
python labels/annotate.py
python scripts/rejudge.py labels/batch1_ai_labelled.jsonl --judge-llm gemini:gemini-3.5-flash-lite \
  --out labels/batch1_ai_rejudged.jsonl
arl label agreement labels/batch1_ai_rejudged.jsonl
```
