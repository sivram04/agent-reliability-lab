"""Redaction of target secrets from anything the lab stores or publishes.

Results are redacted when they are saved, so reports, the dashboard, exports, label files and MCP answers
built from stored results never contain a secret, even one the agent leaked. The leak itself stays visible:
the no_secret_leak check fails and the reply shows [REDACTED] where the secret was.
"""

from __future__ import annotations

import json
import re

from .models import RunResult

MARK = "[REDACTED]"


def redactor(secrets: list[str]):
    pats = [re.compile(re.escape(s), re.IGNORECASE) for s in sorted({s for s in secrets if s}, key=len, reverse=True)]

    def clean(text: str) -> str:
        for p in pats:
            text = p.sub(MARK, text)
        return text
    return clean


def redact_results(results: list[RunResult], secrets: list[str]) -> list[RunResult]:
    if not any(secrets):
        return results
    clean = redactor(secrets)
    # Round-trip through JSON text so every nested string (transcripts, tool calls, spans, checks) is covered.
    return [RunResult.model_validate(json.loads(clean(r.model_dump_json()))) for r in results]
