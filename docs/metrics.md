# Metrics

Every run reports:

| Metric | Meaning |
|---|---|
| `pass_rate`, `pass_rate_ci95` | share of scenario runs where every check passed, with a Wilson 95% interval |
| `by_category` | pass rate per category |
| `injection_resistance` | pass rate on `prompt_injection` |
| `safety_violation_rate` | fail rate on `adversarial_user`, `prompt_injection` and `privacy` |
| `recovery_rate` | pass rate of runs where at least one fault fired |
| `hallucination_rate` | fail rate of factual judge rubrics (`helpfulness`, `faithfulness`) |
| `loop_rate` | runs that exceeded `max_tool_calls` |
| `crash_rate` | runs where the agent raised an error |
| `tool_calls_per_run` | mean tool calls |
| `p95_latency_s` | 95th-percentile run latency |
| `usage` | tokens and estimated cost per role |

## Checks
Deterministic checks run first: `contains:*`, `forbidden:*`, `no_secret_leak`, `latency`, `tool_called:*`,
`tool_forbidden:*`, `max_tool_calls`, `user_goal`, plus plugin checks. Only runs that pass all of them are
sent to the LLM judges (`judge:<rubric>`), which keeps judge cost down.

## Judge agreement
LLM judges are only useful if they agree with people. Export judged runs, label them, and measure
agreement and Cohen's kappa with `arl label` ([Scenarios](scenarios.md#labels-and-judge-agreement)).
