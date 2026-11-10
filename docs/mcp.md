# MCP server

`arl mcp` serves the lab over MCP (stdio), so an AI assistant can test your agent and explain what broke.

```bash
pip install "agent-reliability-lab[mcp]"
```

Client config (Claude Desktop, Claude Code, Cursor, VS Code):
```json
{"mcpServers": {"arl": {"command": "arl", "args": ["mcp"]}}}
```

| Tool | What it does |
|---|---|
| `check` | fast change-aware check (no LLM cost): new failures and fixes since the last check |
| `list_suites` | built-in packs and their sizes |
| `init_project` | scaffold `arl/target.yaml`, a starter scenario and a workflow |
| `run_suite` | run a suite on a target; returns summary metrics and failing conversations |
| `list_runs` | recent runs with pass rates |
| `run_failures` | failing conversations of a past run, with the checks that failed |
| `compare_runs` | statistical comparison; `regression: true` means block the deploy |

Example prompt: *"Run the safety pack on arl/target.yaml and tell me which attacks got through and why."*

Target secrets are redacted in everything the server returns.

!!! note
    Testing an agent that is itself an MCP server is a different feature: use `adapter: mcp` in the
    target ([Targets](targets.md#mcp)).
