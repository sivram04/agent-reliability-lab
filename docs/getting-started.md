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
arl init                 # run it in your agent's project: it finds the agent and configures the target
```
Run it after your agent's code exists. It detects the agent (`arl detect` shows what it found) and writes
`arl/target.yaml`, `arl/scenarios/example_task.yaml` and `.github/workflows/agent-reliability.yml`.
Existing files are never overwritten (`--force` overwrites but keeps your canary). If nothing is detected
you get an HTTP template to edit, and `arl check` reports "not reachable" until that server is running.

## 3. Describe your agent
`arl init` finds your agent and writes `arl/target.yaml` with a unique canary (`ARL-CANARY-...`). Add the
sentence it prints to your system prompt (`arl canary` shows it again). Every reply is checked for it. See [Targets](targets.md).

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
