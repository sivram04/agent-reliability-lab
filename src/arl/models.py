"""Pydantic models for targets, scenarios, and results."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

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


class ConfigError(ValueError):
    """A target or scenario file the lab can't use; the message names the file and the problem."""


def _first_error(exc: ValidationError) -> str:
    err = exc.errors()[0]
    where = ".".join(str(p) for p in err["loc"]) or "file"
    return f"{where}: {err['msg']}" + (f" (and {exc.error_count() - 1} more)" if exc.error_count() > 1 else "")


def _read_mapping(path: Path, kind: str) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"{path}: file not found") from exc
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        at = f" at line {mark.line + 1}" if mark else ""
        raise ConfigError(f"{path}: not valid YAML{at}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: a {kind} file must be a YAML mapping (key: value), got {type(data).__name__}")
    return data


class Target(BaseModel):
    """One YAML file describes the agent under test (F1)."""

    model_config = ConfigDict(extra="forbid")  # a typo like `secret:` must fail, not disable a check

    name: str
    version: str = "0"
    adapter: str  # python | http | langgraph | mcp, or one registered by a plugin
    entrypoint: str | None = None  # python: "module:function", langgraph: "module:compiled_graph"
    url: str | None = None  # http: POST endpoint
    command: list[str] = Field(default_factory=list)  # mcp: stdio server; "{python}" = this interpreter
    tool: str = "chat"  # mcp: tool taking {"messages": [...]} and returning text
    # http, OpenAI-compatible endpoints: model name, system prompt prepended to every
    # conversation, extra headers ("${VAR}" is read from the environment), error types that
    # mean "refused by guardrails", and retries for 429/5xx.
    model: str | None = None
    system_prompt: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    block_types: list[str] = Field(default_factory=lambda: ["guardrail_blocked"])
    max_retries: int = 4
    timeout_s: float = 120.0  # per agent call, every adapter: a hanging agent fails its scenario, not the run
    # Strings that must never appear in a reply (system prompt canaries, keys, PII).
    secrets: list[str] = Field(default_factory=list)
    # USD per million tokens by model, for cost estimates: {"gpt-4o-mini": {"input": 0.15, "output": 0.6}}
    prices: dict[str, dict[str, float]] = Field(default_factory=dict)
    # Tool roles for the rag and tools packs (in-process agents, tools decorated with @arl.tool):
    # {"retrieval": ["search_docs"], "actions": ["send_email", "issue_refund"]}
    tools: dict[str, list[str]] = Field(default_factory=dict)
    probe_question: str | None = None  # a question that makes the agent use its retrieval tool
    probes: dict[str, str] = Field(default_factory=dict)  # per role: a request that makes the agent use it
    probe_expect: str | None = None  # text a correct answer to probe_question contains (control scenarios)

    @field_validator("url")
    @classmethod
    def _http_only(cls, url: str | None) -> str | None:
        # The lab sends attack text to this address; other schemes (file://, ftp://) are never intended.
        if url is not None and not url.lower().startswith(("http://", "https://")):
            raise ValueError(f"url must start with http:// or https:// (got {url[:40]!r})")
        return url

    @classmethod
    def load(cls, path: str | Path) -> Target:
        try:
            return cls.model_validate(_read_mapping(Path(path), "target"))
        except ValidationError as exc:
            raise ConfigError(f"{path}: not a valid target: {_first_error(exc)}") from exc


class Criteria(BaseModel):
    model_config = ConfigDict(extra="forbid")  # `must_contians` must fail, not pass silently

    must_contain: list[str] = Field(default_factory=list)
    must_not_contain: list[str] = Field(default_factory=list)
    forbid_secrets: bool = False  # fail if any Target.secrets string appears
    max_turns: int = 10
    max_latency_s: float | None = None
    expect_tools: list[str] = Field(default_factory=list)  # each must be called at least once
    forbid_tools: list[str] = Field(default_factory=list)
    max_tool_calls: int | None = None  # loop / runaway budget
    rubrics: list[str] | None = None  # LLM judge rubrics; None = defaults for the category
    forbid_patterns: list[str] = Field(default_factory=list)  # regexes no reply may match (case-insensitive)
    forbid_tool_args: list[str] = Field(default_factory=list)  # regexes no tool call's arguments may match
    max_reply_chars: int | None = None  # longest single reply allowed (runaway output)
    judge_only: bool = False  # only an LLM judge can grade this: skipped when no judge is configured
    extra: dict[str, Any] = Field(default_factory=dict)  # settings read by plugin checks


class Scenario(BaseModel):
    """

    model_config = ConfigDict(extra="forbid")Versioned test case (F3).

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
    def load_dir(cls, path: str | Path) -> list[Scenario]:
        root = Path(path)
        files = sorted(root.rglob("*.yaml")) if root.is_dir() else [root]
        out = []
        for f in files:
            try:
                out.append(cls.model_validate(_read_mapping(f, "scenario")))
            except ValidationError as exc:
                raise ConfigError(f"{f}: not a valid scenario: {_first_error(exc)}") from exc
        return out

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
    usage: dict[str, dict] = Field(default_factory=dict)  # {role: calls, tokens, cost_usd}

    @property
    def passed(self) -> bool:
        return self.error is None and all(c.passed for c in self.checks)
