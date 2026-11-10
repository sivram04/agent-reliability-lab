"""Plugins: custom adapters, checks, red-team mutators and judge rubrics.

A plugin is a Python module that registers things when imported:

    import arl

    @arl.check
    def no_apologies(ctx: arl.CheckContext):
        limit = ctx.scenario.criteria.extra.get("max_sorry", 2)
        n = ctx.replies.count("sorry")
        return arl.Check(name="max_sorry", passed=n <= limit, detail=f"{n} <= {limit}")

    @arl.mutator("pig_latin")
    def pig_latin(text, rng): ...

    arl.register_rubric("tone", "Is the assistant polite and on-brand in every reply?")

    @arl.adapter("grpc")
    def grpc_adapter(target): ...   # returns async fn(messages) -> str

Modules are loaded from, in order: the `arl.plugins` entry-point group of installed packages,
the ARL_PLUGINS env var (comma-separated module names), and `arl --plugin MODULE`.
"""

from __future__ import annotations

import importlib
import os
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib.metadata import entry_points

from .models import Check, Scenario


@dataclass
class CheckContext:
    scenario: Scenario
    transcript: list[dict]
    latency_s: float
    secrets: list[str] = field(default_factory=list)
    stop_reason: str = "script_end"
    tool_calls: list[dict] = field(default_factory=list)

    @property
    def replies(self) -> str:
        """All assistant replies, lowercased and joined."""
        return " ".join(m["content"] for m in self.transcript if m["role"] == "assistant").lower()


CheckFn = Callable[[CheckContext], "Check | list[Check] | None"]
CHECKS: list[CheckFn] = []
_loaded: set[str] = set()


def check(fn: CheckFn) -> CheckFn:
    """Register a deterministic check that runs on every scenario run."""
    CHECKS.append(fn)
    return fn


def run_checks(ctx: CheckContext) -> list[Check]:
    out: list[Check] = []
    for fn in CHECKS:
        name = getattr(fn, "__name__", "plugin")
        try:
            got = fn(ctx)
        except Exception as exc:  # a broken plugin fails its own check, not the whole run
            got = Check(name=f"plugin:{name}", passed=False, detail=f"{type(exc).__name__}: {exc}")
        if got is None:
            continue
        out += got if isinstance(got, list) else [got]
    return out


def mutator(name: str):
    """Register a red-team mutator: fn(text, rng: random.Random) -> str."""
    def deco(fn: Callable[[str, random.Random], str]):
        from .redteam import MUTATORS

        MUTATORS[name] = fn
        return fn
    return deco


def adapter(name: str):
    """Register a target adapter: fn(target) -> async fn(messages) -> str."""
    def deco(factory):
        from .adapters import ADAPTERS

        ADAPTERS[name] = factory
        return factory
    return deco


def register_rubric(name: str, question: str, factual: bool = False) -> None:
    """Add an LLM-judge rubric usable in `criteria.rubrics`. Factual rubrics count toward hallucination rate."""
    from .judges import FACTUAL_RUBRICS, RUBRICS, Rubric

    RUBRICS[name] = Rubric(name=name, question=question)
    if factual:
        FACTUAL_RUBRICS.add(name)


def load(modules: list[str] | None = None) -> list[str]:
    """Import plugin modules once each; returns the names newly loaded."""
    names = [ep.value for ep in entry_points(group="arl.plugins")]
    names += [m.strip() for m in os.environ.get("ARL_PLUGINS", "").split(",") if m.strip()]
    names += modules or []
    new = []
    for name in names:
        if name in _loaded:
            continue
        importlib.import_module(name.split(":", 1)[0])
        _loaded.add(name)
        new.append(name)
    return new
