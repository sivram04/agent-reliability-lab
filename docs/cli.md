# CLI

Run `arl COMMAND --help` for every option.

| Command | Purpose |
|---|---|
| `arl init` | scaffold a target, a starter scenario and a CI workflow |
| `arl suites` | list built-in scenario packs |
| `arl run` | run a suite against a target (`--repeats`, `--user-llm`, `--judge-llm`, `--junit-out`, `--results-out`, `--json-out`, `--min-pass-rate`, `--cassette`/`--record-mode`, `--otel`) |
| `arl runs` | list past runs |
| `arl compare BASE NEW` | statistical comparison; exit code 1 on regression |
| `arl report RUN` | HTML report with step-by-step trace replay |
| `arl dashboard` | static dashboard across runs and versions |
| `arl ci-summary` | Markdown summary for PR comments |
| `arl redteam` | generate attack variants that breach the target |
| `arl label export / annotate / agreement` | human labels and judge agreement |
| `arl mcp` | serve the lab over MCP |

Global options: `--version`, `--plugin MODULE` (repeatable).

## Record and replay
```bash
arl run ... --cassette c.json --record-mode record
arl run ... --cassette c.json --record-mode replay   # offline, exact: agent, user, judge and tool calls
```
