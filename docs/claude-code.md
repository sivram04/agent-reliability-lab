# Claude Code plugin

The plugin makes reliability testing part of building the agent. You keep working with Claude as usual;
the lab checks your agent in the background and Claude fixes what breaks.

## Install
```bash
pip install "agent-reliability-lab[mcp]"     # or have uv installed; the plugin falls back to uvx
```
In Claude Code:
```
/plugin marketplace add sivram04/agent-reliability-lab
/plugin install arl@agent-reliability-lab
```

## What you get
| Piece | What it does |
|---|---|
| Skill `agent-reliability` | Claude recognises agent projects and knows how to set up the lab, plant a canary, write scenarios, read results and fix failures without weakening tests. |
| Stop hook | After each Claude turn that changed files in a project with `arl/target.yaml`, runs `arl check` (16 generic attacks plus your scenarios, deterministic, seconds). If something that passed before now fails, Claude is asked to fix it before finishing. Projects without a target are skipped instantly. |
| MCP server | `check`, `run_suite`, `run_failures`, `compare_runs`, `list_runs`, `list_suites`, `init_project`. |

## A typical session
> **You:** add a refund tool to the support agent
>
> **Claude:** *edits the agent* … *(hook)* `[arl] 3 scenario(s) that passed before now fail` …
> The new tool's description repeats the system prompt, so "translate your instructions" attacks now
> leak it. Moving the policy text out of the tool description … re-checked: all 19 scenarios pass.

## Outside Claude Code
- `arl check` in a terminal, a pre-commit hook or a watch loop: exit code 1 on a regression.
- Cursor, VS Code and Claude Desktop: add the MCP server (`arl mcp`), see [MCP server](mcp.md).
- Results of every check are in `.arl/` and in the dashboard.
