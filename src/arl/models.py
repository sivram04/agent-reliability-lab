"""Pydantic models for targets, scenarios, and results."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

Category = Literal[
    "task_success",
    "adversarial_user",
    "prompt_injection",
    "tool_chaos",
    "knowledge_conflict",
    "cost_loop",
    "privacy",
]


class Target(BaseModel):
    """One YAML file describes the agent under test (F1)."""

    name: str
    version: str = "0"
    adapter: Literal["python", "http", "langgraph", "mcp"]
    entrypoint: str | None = None  # python: "module:function", langgraph: "module:compiled_graph"
    url: str | None = None  # http: POST endpoint
    command: list[str] = Field(default_factory=list)  # mcp: stdio server; "{python}" = this interpreter
    tool: str = "chat"  # mcp: tool taking {"messages": [...]} and returning text
    timeout_s: float = 30.0

    @classmethod
    def load(cls, path: str | Path) -> "Target":
        return cls.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


class Criteria(BaseModel):
    must_contain: list[str] = Field(default_factory=list)
    must_not_contain: list[str] = Field(default_factory=list)
    max_turns: int = 10
    max_latency_s: float | None = None


class Scenario(BaseModel):
    """Versioned test case (F3). Simulated multi-turn users come in Phase 2."""

    id: str
    version: int = 1
    category: Category
    goal: str
    turns: list[str]
    criteria: Criteria = Field(default_factory=Criteria)

    @classmethod
    def load_dir(cls, path: str | Path) -> list["Scenario"]:
        root = Path(path)
        files = sorted(root.rglob("*.yaml")) if root.is_dir() else [root]
        return [cls.model_validate(yaml.safe_load(f.read_text(encoding="utf-8"))) for f in files]


class Check(BaseModel):
    name: str
    passed: bool
    detail: str = ""


class RunResult(BaseModel):
    scenario_id: str
    category: Category
    repeat: int
    seed: int
    transcript: list[dict]
    checks: list[Check]
    latency_s: float
    error: str | None = None
    spans: list[dict] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.error is None and all(c.passed for c in self.checks)
