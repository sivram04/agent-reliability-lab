"""SQLite results store. Postgres (Neon) comes later behind the same API."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .models import RunResult, Target

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, target TEXT, version TEXT, created_at TEXT, summary TEXT
);
CREATE TABLE IF NOT EXISTS results (
    run_id TEXT, scenario_id TEXT, category TEXT, repeat INTEGER, seed INTEGER,
    passed INTEGER, latency_s REAL, error TEXT, checks TEXT, transcript TEXT, spans TEXT
);
"""


class Store:
    def __init__(self, path: str | Path = "arl.db"):
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)

    def save_run(self, target: Target, results: list[RunResult], summary: dict) -> str:
        run_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()
        with self.conn:
            self.conn.execute(
                "INSERT INTO runs VALUES (?, ?, ?, ?, ?)",
                (run_id, target.name, target.version, now, json.dumps(summary)),
            )
            self.conn.executemany(
                "INSERT INTO results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        run_id, r.scenario_id, r.category, r.repeat, r.seed, int(r.passed),
                        r.latency_s, r.error,
                        json.dumps([c.model_dump() for c in r.checks]), json.dumps(r.transcript),
                        json.dumps(r.spans),
                    )
                    for r in results
                ],
            )
        return run_id

    def list_runs(self) -> list[tuple]:
        return self.conn.execute(
            "SELECT id, target, version, created_at, summary FROM runs ORDER BY created_at DESC"
        ).fetchall()

    def close(self) -> None:
        self.conn.close()
