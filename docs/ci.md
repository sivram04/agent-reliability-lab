# CI gating

## GitHub Actions
```yaml
- uses: sivram04/agent-reliability-lab@v1
  with:
    target: arl/target.yaml
    suite: builtin:safety,arl/scenarios
    repeats: "3"
    baseline: arl/baseline.json   # from `arl run ... --results-out`; empty = report only
    alpha: "0.05"                 # significance level
    max-drop: "0.0"               # ignore smaller pass-rate drops
    extra-args: --judge-llm gemini:gemini-3.5-flash-lite
```
The action runs the suite, writes the HTML report, compares against the baseline, posts or updates a PR
comment and the job summary, and fails the job on a significant regression. The output `regression` is
`'true'` or `'false'`.

## How the gate decides
For overall and per-category pass rates, a one-sided Fisher exact test asks whether the new version fails
more often than the baseline. Latency uses a Mann-Whitney U test. A metric is a regression when p < alpha
and the drop exceeds `max-drop`. Use `--repeats 3` or more so the tests have enough runs to decide.

## Any other CI
```bash
arl run --target arl/target.yaml --suite builtin:safety --results-out new.json --junit-out arl.xml
arl compare arl/baseline.json new.json      # exit code 1 on regression
```
GitLab, Jenkins, Azure Pipelines and CircleCI read `arl.xml` natively. Target secrets are replaced with
`[REDACTED]` in the XML.

`--min-pass-rate 0.95` fails the run outright below a fixed threshold.
