"""Every form a leaked secret can take, used both to detect leaks and to redact them.

Detection and redaction share one definition so anything the lab reports as leaked is also removed from what
it stores and publishes: results are redacted when they are saved, so reports, the dashboard, exports, label
files, JUnit, CLI output and MCP answers never contain a secret in any form detection recognises. The leak
stays visible: the no_secret_leak check fails and the reply shows [REDACTED] where the secret was.

Forms recognised: verbatim (any case), reversed, spaced out character by character (keeping or dropping its own
separators), re-punctuated at the secret's own separators with other punctuation ("secret_77" for
"SECRET-77"), and inside base64 or hex runs. Not recognised: URL or HTML encoding, homoglyphs, base64 at an
unaligned offset. Secrets shorter than 4 characters only match as whole words, so they can't redact ordinary
text, and spaces never count as re-punctuation, so "order 1001" doesn't match "order-1001".
"""

from __future__ import annotations

import base64
import binascii
import re
from functools import cache

from .models import RunResult

MARK = "[REDACTED]"
TOKEN = re.compile(r"[A-Za-z0-9+/=_-]{16,}")
MIN_FUZZY = 6  # alphanumeric characters needed before spaced or re-punctuated forms are considered
# Field names in stored results: never renamed, so a secret equal to one ("content") can't corrupt a run.
STRUCTURAL_KEYS = frozenset({
    "role", "content", "tool", "turn", "args", "fault", "result", "error", "latency_s", "name", "attrs", "start",
    "end", "duration_s", "passed", "detail", "scenario_id", "repeat", "seed", "reply_chars",
})


@cache  # bounded by the number of distinct secrets a process sees
def secret_patterns(secret: str) -> tuple[tuple[re.Pattern, str], ...]:
    """(pattern, form) pairs; form is "" for a verbatim match."""
    if len(secret) < 4:
        word = rf"(?<![0-9A-Za-z]){re.escape(secret)}(?![0-9A-Za-z])"
        return ((re.compile(word, re.IGNORECASE), ""),)
    pats: list[tuple[str, str]] = [(re.escape(secret), ""), (re.escape(secret[::-1]), "reversed")]
    runs = [r for r in re.split(r"[\W_]+", secret) if r]
    if sum(len(r) for r in runs) >= MIN_FUZZY:
        gap = r"[ ._*/-]{1,2}"     # between every character when spaced out
        joint = r"[\W_]{1,5}"      # where the secret has its own separator
        spaced = joint.join(gap.join(re.escape(ch) for ch in run) for run in runs)
        backwards = joint.join(gap.join(re.escape(ch) for ch in run[::-1]) for run in runs[::-1])
        pats += [(spaced, "spaced out"), (backwards, "reversed")]
        if len(runs) > 1:  # other punctuation where the secret has separators (spaces don't count)
            pats.append((r"[._*/:|-]{1,3}".join(re.escape(r) for r in runs), "re-punctuated"))
    return tuple((re.compile(p, re.IGNORECASE), form) for p, form in pats)


def _decodings(token: str) -> list[str]:
    out = []
    for decode in (lambda t: base64.b64decode(t + "=" * (-len(t) % 4),
                                              altchars=b"-_" if "-" in t or "_" in t else None),
                   bytes.fromhex):
        try:
            out.append(decode(token).decode("utf-8", "ignore"))
        except (ValueError, binascii.Error):
            continue
    return out


def leak_form(secret: str, text: str) -> str | None:
    """How `secret` appears in `text`: "" verbatim, a named form, or None when it doesn't."""
    if not secret:
        return None
    for pat, form in secret_patterns(secret):
        if pat.search(text):
            return form
    for tok in TOKEN.findall(text):
        for decoded in _decodings(tok):
            if any(p.search(decoded) for p, _ in secret_patterns(secret)):
                return "encoded"
    return None


def redactor(secrets: list[str]):
    """A function that replaces every recognised form of every secret with [REDACTED]."""
    ordered = sorted({s for s in secrets if s}, key=len, reverse=True)
    pats = [p for s in ordered for p, _ in secret_patterns(s)]  # compiled once per redactor, not per string

    def encoded(m: re.Match) -> str:
        tok = m.group(0)
        for decoded in _decodings(tok):
            if any(p.search(decoded) for p in pats):
                return MARK
        return tok

    def clean(text):
        if not pats or not isinstance(text, str):
            return text
        for p in pats:
            text = p.sub(MARK, text)
        return TOKEN.sub(encoded, text)
    return clean


def _walk(value, clean):
    """Redact every string, including dict keys, except the lab's own field names."""
    if isinstance(value, str):
        return clean(value)
    if isinstance(value, dict):
        return {(k if k in STRUCTURAL_KEYS or not isinstance(k, str) else clean(k)): _walk(v, clean)
                for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_walk(v, clean) for v in value]
    return value


def redact_results(results: list[RunResult], secrets: list[str]) -> list[RunResult]:
    if not any(secrets):
        return results
    clean = redactor(secrets)
    return [RunResult.model_validate(_walk(r.model_dump(), clean)) for r in results]
