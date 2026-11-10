"""Plain, wide terminal output in every environment, so CLI messages are never wrapped or coloured in tests."""

import os

os.environ.update({"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "200"})
os.environ.pop("FORCE_COLOR", None)
os.environ.pop("GITHUB_ACTIONS", None)  # rich forces colour on Actions
