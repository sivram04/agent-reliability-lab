"""VCR-style cassettes for deterministic replay (N1).

Each agent call is keyed by (scenario, repeat, turn). Record mode calls the
real agent and saves the reply or the exception. Replay mode never touches the
agent: it returns the saved reply, re-raises the saved error, and fails loudly
when the request differs from what was recorded.
"""

from __future__ import annotations

import hashlib
import json
from contextvars import ContextVar
from pathlib import Path
from typing import Literal

from .adapters import Agent

Mode = Literal["off", "record", "replay"]

# Set by the runner so the cassette knows which call it is serving.
call_context: ContextVar[tuple[str, int, int]] = ContextVar("arl_call_context")


class CassetteMiss(Exception):
    """Replay asked for a call that was never recorded, or whose request changed."""


def _digest(messages: list[dict]) -> str:
    return hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest()[:16]


def _replayed_error(type_name: str, message: str) -> Exception:
    # Same class name as the original, so RunResult.error matches exactly.
    return type(type_name, (Exception,), {})(message)


class Cassette:
    def __init__(self, path: str | Path, mode: Mode):
        self.path = Path(path)
        self.mode = mode
        self.entries: dict[str, dict] = {}
        if mode == "replay":
            self.entries = json.loads(self.path.read_text(encoding="utf-8"))["entries"]

    def wrap(self, agent: Agent) -> Agent:
        if self.mode == "off":
            return agent

        async def call(messages: list[dict]) -> str:
            scenario_id, repeat, turn = call_context.get()
            key = f"{scenario_id}#{repeat}#{turn}"
            digest = _digest(messages)
            if self.mode == "replay":
                entry = self.entries.get(key)
                if entry is None or entry["request"] != digest:
                    raise CassetteMiss(f"no recorded call for {key} with this request")
                if "error" in entry:
                    raise _replayed_error(entry["error"]["type"], entry["error"]["message"])
                return entry["reply"]
            try:
                reply = await agent(messages)
            except Exception as exc:
                self.entries[key] = {
                    "request": digest,
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                }
                raise
            self.entries[key] = {"request": digest, "reply": reply}
            return reply

        return call

    def save(self) -> None:
        if self.mode == "record":
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = {"version": 1, "entries": dict(sorted(self.entries.items()))}
            self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
