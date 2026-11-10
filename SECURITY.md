# Security policy

## Reporting a vulnerability
Please report vulnerabilities privately through GitHub's "Report a vulnerability" button on the Security tab.
Do not open a public issue. You can expect a first reply within 7 days.

## Scope
- The `arl` package, CLI, GitHub Action and Docker image.
- Leaks of API keys or target secrets into reports, cassettes, traces or logs are in scope and treated as high
  severity.

## Notes for users
- Attack scenarios are text sent to your agent. Run the lab against test environments, not production.
- Cassettes and reports contain full transcripts. Treat them like logs, and keep real secrets out of
  `secrets:` lists in committed target files (use `${ENV_VAR}` expansion).
