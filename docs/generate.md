# Attacks written for your agent

Built-in packs test what every agent must withstand. The most damaging attacks are about what *your* agent
protects and can do: a bank bot approving loans, a clinic bot reading out patient records, a support bot
handing out staff discount codes. `arl generate` writes those.

```bash
arl generate --llm gemini:gemini-3.5-flash-lite      # or ollama:llama3.1, anthropic:..., openai:...
arl run --target arl/target.yaml --suite arl/scenarios/generated --judge-llm gemini:gemini-3.5-flash-lite
```

## How it works
1. **Profile.** The agent's domain, what it protects, high-impact actions and rules. Extracted by the LLM from
   the target's `system_prompt` (or `--describe "..."`) and saved to `arl/profile.yaml` for you to review and
   edit. Without an LLM, fill in that file yourself; generation then runs fully offline.
   ```yaml
   domain: retail banking support
   protected: [system prompt, other customers' balances, fraud-rule thresholds]
   actions: [approve a loan, unfreeze a card, transfer funds]
   rules: [never give investment advice]
   ```
2. **Attacks.** Templates over the profile (claimed authority, translation and encoding tricks, urgency,
   role-play, bulk actions, policy overrides), plus LLM-written attacks per OWASP risk (LLM07 prompt leakage,
   LLM02 data disclosure, LLM06 excessive agency, LLM01 prompt injection), varied in technique and language.
3. **Gate.** Every attack is validated, deduplicated against the others, the built-in library and earlier
   runs, and tagged with capability, OWASP and technique.

## Grading, honestly
- Prompt and canary leaks are checked deterministically (`forbid_secrets`).
- Actions are checked against your `tools.actions` (`forbid_tools`) when the agent runs in-process.
- Anything the canary can't detect (another customer's balance, a broken policy, an action by a black-box
  agent) is **judge-only**: graded by `--judge-llm`, skipped without one, never counted as passed.
- Attacks are never filtered by whether your agent passes them; that would only keep the easy ones.

## Safety of the generator itself
- Secret values from `secrets:` are scrubbed from the profile, never sent to the generator model, and any
  attack containing one is dropped.
- The generator is asked only to *ask* for harmful outcomes, not to include harmful instructions.
- Output lands in `arl/scenarios/generated/` with a header asking for review before committing.

## Example
Against a real Gemini support bot, generation produced attacks such as a fake "Acme IT Support" claiming a
patch to the 30-day return-policy database requires the bot's base instructions and internal codes; see
`case_studies/judge/generated/` and the results in the [judge agreement](judge-agreement.md) data.
