# LLM providers and cost

The lab's own models (simulated user, judge, red-team paraphraser) take a spec string:

| Spec | Endpoint | Key |
|---|---|---|
| `openai:gpt-4o-mini` | api.openai.com | `OPENAI_API_KEY` |
| `anthropic:claude-haiku-5-5` | Anthropic Messages API | `ANTHROPIC_API_KEY` |
| `gemini:gemini-3.5-flash-lite` | Gemini OpenAI-compatible endpoint | `GEMINI_API_KEY` |
| `groq:llama-3.1-8b-instant` | Groq | `GROQ_API_KEY` |
| `openrouter:MODEL` | OpenRouter | `OPENROUTER_API_KEY` |
| `ollama:llama3.1` | local Ollama (`OLLAMA_HOST`) | none |
| `openai` | any OpenAI-compatible URL | `ARL_LLM_BASE_URL`, `ARL_LLM_MODEL`, `ARL_LLM_API_KEY` |
| `python:module:fn` | a local function | none |

Judges run at temperature 0 so verdicts repeat.

!!! tip "Judging attacks"
    Point the judge at the provider directly, not through your own guardrail gateway: judge prompts
    quote the attacks and a guardrail will block them.

## Rate limits
- `ARL_LLM_CONCURRENCY`: parallel lab LLM calls (default 2).
- `ARL_LLM_RPM`: requests per minute (unset = no pacing). For free tiers, set it a little under the limit.
- 429 and 5xx responses are retried with backoff (up to 60 s). If the judge still fails, that run is left
  unjudged rather than aborting the suite.

## Tokens and cost
Every run reports tokens per role: `agent` (from OpenAI-style `usage` in HTTP responses), `user`, `judge`,
`generator`, and `all`. Costs are only estimated when the price is known:

- `prices:` in the target YAML, or a YAML file in `ARL_PRICES_FILE`, with the same shape:
  `{model: {input: USD per 1M, output: USD per 1M}}`
- Ollama models count as free.

Unknown prices show as `cost n/a` instead of a guess.
