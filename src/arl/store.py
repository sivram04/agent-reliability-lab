"""SQLite results store. Postgres (Neon) comes later behind the same API."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .models import Check, RunResult, Target

RUN_COLS = {"id": "TEXT PRIMARY KEY", "target": "TEXT", "version": "TEXT", "created_at": "TEXT",
            "summary": "TEXT", "suite": "TEXT", "source": "TEXT"}  # source: cli | check | mcp | ci
RESULT_COLS = {
    "run_id": "TEXT", "scenario_id": "TEXT", "category": "TEXT", "repeat": "INTEGER",
    "seed": "INTEGER", "passed": "INTEGER", "latency_s": "REAL", "error": "TEXT", "checks": "TEXT",
    "transcript": "TEXT", "spans": "TEXT", "stop_reason": "TEXT", "tool_calls": "TEXT", "faults_fired": "INTEGER",
}


# Fixed statements built once from the constant column list above; values are always bound parameters.
INSERT_RESULT = (f"INSERT INTO results ({', '.join(RESULT_COLS)}) "  # nosec B608 - constant column names
                 f"VALUES ({', '.join('?' * len(RESULT_COLS))})")
SELECT_RESULTS = f"SELECT {', '.join(RESULT_COLS)} FROM results WHERE run_id = ?"  # nosec B608 - constant columns


class Store:
    def __init__(self, path: str | Path = "arl.db"):
        self.conn = sqlite3.connect(path)
        for table, cols in (("runs", RUN_COLS), ("results", RESULT_COLS)):
            self.conn.execute(
                f"CREATE TABLE IF NOT EXISTS {table} ({', '.join(f'{k} {v}' for k, v in cols.items())})"
            )
            # Add columns introduced after a database was created.
            have = {row[1] for row in self.conn.execute(f"PRAGMA table_info({table})")}
            for k, v in cols.items():
                if k not in have:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {k} {v.split()[0]}")
        # Results are always read by run; without this, every lookup scans the whole history.
        self.conn.execute("CREATE INDEX IF NOT EXISTS results_by_run ON results (run_id)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS runs_by_created ON runs (created_at)")

    def save_run(self, target: Target, results: list[RunResult], summary: dict, suite: str = "",
                 source: str = "cli") -> str:
        run_id = uuid.uuid4().hex[:12]
        now = datetime.now(UTC).isoformat()
        with self.conn:
            self.conn.execute(
                "INSERT INTO runs (id, target, version, created_at, summary, suite, source) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, target.name, target.version, now, json.dumps(summary), suite, source),
            )
            self.conn.executemany(
                INSERT_RESULT,
                [
                    (
                        run_id, r.scenario_id, r.category, r.repeat, r.seed, int(r.passed),
                        r.latency_s, r.error,
                        json.dumps([c.model_dump() for c in r.checks]), json.dumps(r.transcript),
                        json.dumps(r.spans), r.stop_reason, json.dumps(r.tool_calls, default=str),
                        r.faults_fired,
                    )
                    for r in results
                ],
            )
        return run_id

    def list_runs(self) -> list[tuple]:
        return self.conn.execute(
            "SELECT id, target, version, created_at, summary FROM runs ORDER BY created_at DESC"
        ).fetchall()

    def get_run(self, run_id: str) -> dict:
        row = self.conn.execute(
            "SELECT id, target, version, created_at, summary, suite FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"no run {run_id}")
        return dict(zip(("id", "target", "version", "created_at", "summary", "suite"), row)) | {
            "summary": json.loads(row[4])
        }

    def load_results(self, run_id: str) -> list[RunResult]:
        rows = self.conn.execute(
            SELECT_RESULTS, (run_id,)
        ).fetchall()
        out = []
        for row in rows:
            d = dict(zip(RESULT_COLS, row))
            out.append(RunResult(
                scenario_id=d["scenario_id"], category=d["category"], repeat=d["repeat"],
                seed=d["seed"], latency_s=d["latency_s"], error=d["error"],
                checks=[Check(**c) for c in json.loads(d["checks"])],
                transcript=json.loads(d["transcript"]), spans=json.loads(d["spans"] or "[]"),
                stop_reason=d["stop_reason"] or "script_end",
                tool_calls=json.loads(d["tool_calls"] or "[]"), faults_fired=d["faults_fired"] or 0,
            ))
        return out

    def latest_run(self, target: str, before: str | None = None) -> str | None:
        """Most recent run id for a target name, optionally excluding one run."""
        row = self.conn.execute(
            "SELECT id FROM runs WHERE target = ? AND id != ? ORDER BY created_at DESC LIMIT 1",
            (target, before or ""),
        ).fetchone()
        return row[0] if row else None

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self.conn.close()
