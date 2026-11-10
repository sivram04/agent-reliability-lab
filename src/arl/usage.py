"""Token and cost accounting.

Every LLM call the lab makes (simulated user, judge, generator) and every OpenAI-style
agent response that reports `usage` is recorded against the scenario run in progress.
Costs are only estimated when a price is known: from the target's `prices`, the
ARL_PRICES_FILE YAML, or 0 for local models. Unknown prices stay None rather than guessed.
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from pathlib import Path

import yaml

# Per-scenario-run meter: {role: {"calls", "input_tokens", "output_tokens", "cost_usd"}}
current_usage: ContextVar[dict | None] = ContextVar("arl_usage", default=None)

# USD per million tokens, {model: {"input": x, "output": y}}. Local runtimes cost nothing.
FREE_PREFIXES = ("ollama/", "local/", "python:")
_prices: dict[str, dict[str, float]] = {}


def load_prices(extra: dict[str, dict[str, float]] | None = None) -> None:
    path = os.environ.get("ARL_PRICES_FILE")
    if path:
        _prices.update(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})
    if extra:
        _prices.update(extra)


def price(model: str | None, input_tokens: int, output_tokens: int) -> float | None:
    if not model:
        return None
    if model.startswith(FREE_PREFIXES):
        return 0.0
    p = _prices.get(model)
    if p is None:
        return None
    return (input_tokens * p.get("input", 0.0) + output_tokens * p.get("output", 0.0)) / 1e6


def record(role: str, model: str | None, input_tokens: int, output_tokens: int) -> None:
    meter = current_usage.get()
    if meter is None:
        return
    row = meter.setdefault(role, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
    row["calls"] += 1
    row["input_tokens"] += input_tokens
    row["output_tokens"] += output_tokens
    cost = price(model, input_tokens, output_tokens)
    if cost is None or row["cost_usd"] is None:
        row["cost_usd"] = None  # one unpriced call makes the total unknown
    else:
        row["cost_usd"] += cost


def total(usages: list[dict]) -> dict:
    """Sum per-run usage dicts into {role: totals} plus an "all" row."""
    out: dict[str, dict] = {}
    for u in usages:
        for role, row in u.items():
            agg = out.setdefault(role, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
            for k in ("calls", "input_tokens", "output_tokens"):
                agg[k] += row[k]
            agg["cost_usd"] = None if agg["cost_usd"] is None or row["cost_usd"] is None else agg["cost_usd"] + row["cost_usd"]
    if out:
        everything = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
        for row in out.values():
            for k in ("calls", "input_tokens", "output_tokens"):
                everything[k] += row[k]
            everything["cost_usd"] = (None if everything["cost_usd"] is None or row["cost_usd"] is None
                                      else everything["cost_usd"] + row["cost_usd"])
        out["all"] = everything
    return out
