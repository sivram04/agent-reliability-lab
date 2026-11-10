# Contributing

Thanks for helping make AI agents more reliable.

## Setup
```bash
git clone https://github.com/sivram04/agent-reliability-lab
cd agent-reliability-lab
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q
ruff check .
```

Tests run offline. Fixture agents (`fixtures/`) and stand-in user and judge models mean no API keys are needed.

## What to work on
- Issues labelled `good first issue`.
- New scenarios: add to `scripts/build_library.py`, rebuild, and include a fixture agent that fails them.
- New mutators, checks or adapters: use the plugin entry points (see `docs/plugins.md`) so they can also live
  in a separate package.

## Pull requests
- One change per PR, with a test that fails without it.
- Keep the core dependency-light. Heavy integrations go behind an optional extra.
- Update `CHANGELOG.md` under "Unreleased".
- `pytest -q` and `ruff check .` must pass.

## Reporting bugs
Open an issue with the `arl --version` output, your target YAML (remove secrets), and the failing command.
Security problems go through [SECURITY.md](SECURITY.md), not public issues.

By contributing you agree that your contributions are licensed under the Apache License 2.0.
