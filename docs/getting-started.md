# Getting started

## 1. Install
```bash
pip install agent-reliability-lab            # core
pip install "agent-reliability-lab[mcp]"     # + MCP adapter and `arl mcp` server
pip install "agent-reliability-lab[langgraph,otel]"
```
Or with Docker: `docker run --rm -v "$PWD:/work" ghcr.io/sivram04/agent-reliability-lab --help`.

## 2. Scaffold
```bash
arl init                 # http target; or --adapter python | langgraph | mcp
```
This writes `arl/target.yaml`, `arl/scenarios/example_task.yaml` and
`.github/workflows/agent-reliability.yml`. Existing files are never overwritten.

## 3. Describe your agent
Edit `arl/target.yaml`. Plant a canary in your system prompt (for example `CANARY-123`) and list it
under `secrets:`. Every reply is checked for it. See [Targets](targets.md).

## 4. Run
```bash
arl suites                                              # built-in packs
arl run --target arl/target.yaml --suite builtin:smoke  # seconds
arl run --target arl/target.yaml --suite builtin:safety,arl/scenarios --repeats 3
```
The output gives a pass rate with a 95% confidence interval, per-category rates and the failing scenarios.

## 5. Add judges and simulated users (optional)
```bash
export GEMINI_API_KEY=...        # or use ollama:llama3.1 for free, local models
arl run --target arl/target.yaml --suite builtin:safety \
  --user-llm gemini:gemini-3.5-flash-lite --judge-llm gemini:gemini-3.5-flash-lite
```

## 6. Read the report
```bash
arl report latest --out reports/run.html
```
Each failing run can be replayed step by step: user turn, agent turn, tool calls, injected faults, judge verdict.

## 7. Gate CI
Commit a baseline (`arl run ... --results-out arl/baseline.json`) and enable the workflow. See [CI gating](ci.md).
