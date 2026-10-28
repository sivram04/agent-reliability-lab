"""Pydantic models for targets, scenarios, and results."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from .faults import Fault

Category = Literal[
    "task_success",
    "adversarial_user",
    "prompt_injection",
    "tool_chaos",
    "knowledge_conflict",
    "cost_loop",
    "privacy",
]

StopReason = Literal["goal_met", "gave_up", "max_turns", "script_end", "error"]


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
    # Strings that must never appear in a reply (system prompt canaries, keys, PII).
    secrets: list[str] = Field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path) -> "Target":
        return cls.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


class Criteria(BaseModel):
    must_contain: list[str] = Field(default_factory=list)
    must_not_contain: list[str] = Field(default_factory=list)
    forbid_secrets: bool = False  # fail if any Target.secrets string appears
    max_turns: int = 10
    max_latency_s: float | None = None
    expect_tools: list[str] = Field(default_factory=list)  # each must be called at least once
    forbid_tools: list[str] = Field(default_factory=list)
    max_tool_calls: int | None = None  # loop / runaway budget


class Scenario(BaseModel):
    """Versioned test case (F3).

    `turns` are scripted user messages, sent first. If `user_goal` is set and a
    user LLM is configured, a simulated user (F4) continues the conversation
    until it reports the goal met, gives up, or hits `criteria.max_turns`.
    """

    id: str
    version: int = 1
    category: Category
    goal: str
    persona: str | None = None
    user_goal: str | None = None
    turns: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    parent: str | None = None  # set on generated variants (F5)
    faults: list[Fault] = Field(default_factory=list)  # injected into @arl.tool calls (F2)
    criteria: Criteria = Field(default_factory=Criteria)

    @classmethod
    def load_dir(cls, path: str | Path) -> list["Scenario"]:
        root = Path(path)
        files = sorted(root.rglob("*.yaml")) if root.is_dir() else [root]
        return [cls.model_validate(yaml.safe_load(f.read_text(encoding="utf-8"))) for f in files]

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.model_dump(exclude_defaults=True), sort_keys=False, allow_unicode=True)


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
    stop_reason: StopReason = "script_end"
    spans: list[dict] = Field(default_factory=list)
    tool_calls: list[dict] = Field(default_factory=list)
    faults_fired: int = 0

    @property
    def passed(self) -> bool:
        return self.error is None and all(c.passed for c in self.checks)
