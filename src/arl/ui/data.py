"""Read-only view of result databases for the dashboard: runs, findings, coverage and replays."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .. import suites, taxonomy
from ..explain import explain, headline
from ..models import RunResult, Scenario
from ..store import Store

DEFAULT_DBS = (".arl/arl.db", "arl.db")
RUNS_QUERY = "SELECT id, target, version, created_at, summary, suite, source FROM runs"
RUNS_QUERY_OLD = "SELECT id, target, version, created_at, summary, suite, 'cli' FROM runs"


def discover(paths: list[str] | None, root: Path = Path(".")) -> list[Path]:
    found = [Path(p) for p in paths] if paths else [root / p for p in DEFAULT_DBS]
    return [p for p in found if p.is_file()]


class Data:
    def __init__(self, dbs: list[Path]):
        self.dbs = dbs
        self._scenarios: dict[str, Scenario] | None = None

    # Runs ---------------------------------------------------------------------------------------
    def runs(self) -> list[dict]:
        out = []
        for db in self.dbs:
            con = sqlite3.connect(db)
            cols = {row[1] for row in con.execute("PRAGMA table_info(runs)")}
            query = RUNS_QUERY if "source" in cols else RUNS_QUERY_OLD  # databases from before run sources
            for rid, target, version, created, summary, suite, src in con.execute(query):
                s = json.loads(summary)
                out.append({"id": rid, "db": str(db), "target": target, "version": version, "created": created,
                            "suite": suite or "", "source": src or "cli", "pass_rate": s.get("pass_rate"),
                            "ci": s.get("pass_rate_ci95"), "runs": s.get("runs"), "passed": s.get("passed"),
                            "scenarios": s.get("scenarios"), "by_category": s.get("by_category", {})})
            con.close()
        return sorted(out, key=lambda r: r["created"], reverse=True)

    def _locate(self, run_id: str) -> Path:
        for db in self.dbs:
            con = sqlite3.connect(db)
            hit = con.execute("SELECT 1 FROM runs WHERE id = ?", (run_id,)).fetchone()
            con.close()
            if hit:
                return db
        raise KeyError(run_id)

    def results(self, run_id: str) -> list[RunResult]:
        store = Store(self._locate(run_id))
        try:
            return store.load_results(run_id)
        finally:
            store.close()

    # Scenario metadata (for coverage and goals) -------------------------------------------------------
    def scenario_index(self) -> dict[str, Scenario]:
        if self._scenarios is None:
            index = {s.id: s for s in suites.load("builtin:deep")}
            for extra in ("arl/scenarios", "case_studies"):
                if Path(extra).is_dir():
                    for path in Path(extra).rglob("*.yaml"):
                        try:
                            s = Scenario.load_dir(path)[0]
                            index.setdefault(s.id, s)
                        except Exception:  # noqa: BLE001  targets and other YAML in the same tree
                            continue
            self._scenarios = index
        return self._scenarios

    # Views ---------------------------------------------------------------------------------------
    def run(self, run_id: str) -> dict:
        meta = next(r for r in self.runs() if r["id"] == run_id)
        store = Store(self._locate(run_id))
        try:
            summary = store.get_run(run_id)["summary"]
            results = store.load_results(run_id)
        finally:
            store.close()
        index = self.scenario_index()
        known = [index[r.scenario_id] for r in results if r.scenario_id in index]
        findings = explain(results)
        rows = []
        for i, r in enumerate(results):
            s = index.get(r.scenario_id)
            rows.append({"idx": i, "scenario": r.scenario_id, "repeat": r.repeat, "category": r.category,
                         "passed": r.passed, "error": r.error, "latency_s": r.latency_s,
                         "failed": [c.name for c in r.checks if not c.passed],
                         "judged": any(c.name.startswith("judge:") for c in r.checks),
                         "faults": r.faults_fired, "goal": s.goal if s else "",
                         "classes": taxonomy.classify(s) if s else {}})
        return {**meta, "summary": summary, "headline": headline(findings, len({r.scenario_id for r in results})),
                "findings": [f.to_dict() for f in findings], "coverage": taxonomy.coverage(known),
                "names": {"capability": taxonomy.CAPABILITIES, "owasp": taxonomy.OWASP_LLM,
                          "agentic": taxonomy.AGENTIC, "out_of_scope": taxonomy.OUT_OF_SCOPE},
                "results": rows}

    def replay(self, run_id: str, idx: int) -> dict:
        r = self.results(run_id)[idx]
        s = self.scenario_index().get(r.scenario_id)
        return {"run": run_id, "idx": idx, "scenario": r.scenario_id, "repeat": r.repeat, "category": r.category,
                "goal": s.goal if s else "", "passed": r.passed, "error": r.error, "latency_s": r.latency_s,
                "stop_reason": r.stop_reason, "transcript": r.transcript, "tool_calls": r.tool_calls,
                "spans": r.spans, "checks": [c.model_dump() for c in r.checks],
                "faults": [f.model_dump() for f in s.faults] if s else []}

    def compare(self, base: str, new: str) -> dict:
        from ..stats import compare

        return compare(self.results(base), self.results(new))

    def bundle(self) -> dict:
        """Everything the app needs, for a static export."""
        runs = self.runs()
        out = {"runs": runs, "run": {}, "replay": {}, "compare": {}}
        for r in runs:
            out["run"][r["id"]] = self.run(r["id"])
            for row in out["run"][r["id"]]["results"]:
                if not row["passed"]:
                    out["replay"][f"{r['id']}/{row['idx']}"] = self.replay(r["id"], row["idx"])
        by_target: dict[str, list[dict]] = {}
        for r in runs:
            by_target.setdefault(r["target"], []).append(r)
        for rs in by_target.values():  # newest vs the run before it, per target
            if len(rs) > 1:
                out["compare"][f"{rs[1]['id']}..{rs[0]['id']}"] = self.compare(rs[1]["id"], rs[0]["id"])
        return out
