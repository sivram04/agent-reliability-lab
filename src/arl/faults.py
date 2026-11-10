"""Tool interception and fault injection (F2).

Decorate an agent's tools with `@arl.tool`. Outside a lab run the decorator is a
no-op. Inside a run, every call goes through the run's ToolBox, which records
it (name, args, result or error, latency, fault) and applies the scenario's
faults deterministically from the run seed.

    from arl import tool

    @tool
    def get_order(order_id: str) -> dict: ...
"""

from __future__ import annotations

import copy
import functools
import random
import time
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any, Literal

from pydantic import BaseModel

FaultMode = Literal[
    "error", "timeout", "latency", "rate_limit", "bad_data", "partial", "schema_drift", "inject", "poison"
]


class Fault(BaseModel):
    tool: str = "*"  # tool name, or "*" for every tool
    mode: FaultMode
    rate: float = 1.0  # probability per call, drawn from the seeded RNG
    first_n: int | None = None  # only the first n calls to the tool (transient faults)
    latency_s: float = 0.0
    payload: str = ""  # inject: text added to the tool output
    data: Any = None  # poison: items/fields merged into the output


class ToolError(Exception):
    """Simulated upstream failure."""


class RateLimitError(ToolError):
    """Simulated HTTP 429."""


current_toolbox: ContextVar[ToolBox | None] = ContextVar("arl_toolbox", default=None)


def _corrupt(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _corrupt(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_corrupt(v) for v in value]
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return -value - 1
    if isinstance(value, str):
        return "corrupted"
    return None


def _partial(value: Any) -> Any:
    if isinstance(value, dict):
        keys = list(value)[: len(value) // 2]
        return {k: value[k] for k in keys}
    if isinstance(value, (list, str)):
        return value[: len(value) // 2]
    return None


def _drift(value: Any) -> Any:
    if isinstance(value, dict):
        return {f"{k}_v2": _drift(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_drift(v) for v in value]
    return value


def _inject(value: Any, payload: str) -> Any:
    if isinstance(value, dict):
        return {**value, "note": payload}
    if isinstance(value, list):
        return [*value, {"source": "external", "text": payload}]
    return f"{value}\n{payload}"


def _poison(value: Any, data: Any) -> Any:
    if isinstance(value, list):
        return [*value, *(data if isinstance(data, list) else [data])]
    if isinstance(value, dict) and isinstance(data, dict):
        return {**value, **data}
    return data


class ToolBox:
    def __init__(self, faults: list[Fault] = (), rng: random.Random | None = None):
        self.faults = list(faults)
        self.rng = rng or random.Random(0)
        self.calls: list[dict] = []
        self.turn = 0  # set by the runner, so reports can place each call in its turn
        self._counts: dict[str, int] = {}

    def _pick(self, name: str) -> Fault | None:
        n = self._counts.get(name, 0)
        for f in self.faults:
            if f.tool not in ("*", name):
                continue
            if f.first_n is not None and n >= f.first_n:
                continue
            if self.rng.random() < f.rate:
                return f
        return None

    def invoke(self, name: str, fn: Callable, *args, **kwargs) -> Any:
        fault = self._pick(name)
        self._counts[name] = self._counts.get(name, 0) + 1
        record = {"tool": name, "turn": self.turn, "args": kwargs or list(args),
                  "fault": fault.mode if fault else None}
        start = time.perf_counter()
        try:
            result = self._apply(fault, fn, args, kwargs)
            record["result"] = result
            return result
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            record["latency_s"] = time.perf_counter() - start
            self.calls.append(record)

    def _apply(self, fault: Fault | None, fn: Callable, args: tuple, kwargs: dict) -> Any:
        if fault is None:
            return fn(*args, **kwargs)
        mode = fault.mode
        if mode == "error":
            raise ToolError("simulated upstream error (HTTP 500)")
        if mode == "timeout":
            raise TimeoutError(f"simulated timeout after {fault.latency_s or 30}s")
        if mode == "rate_limit":
            raise RateLimitError("simulated rate limit (HTTP 429)")
        if mode == "latency":
            time.sleep(fault.latency_s)
            return fn(*args, **kwargs)
        result = copy.deepcopy(fn(*args, **kwargs))
        if mode == "bad_data":
            return _corrupt(result)
        if mode == "partial":
            return _partial(result)
        if mode == "schema_drift":
            return _drift(result)
        if mode == "inject":
            return _inject(result, fault.payload)
        if mode == "poison":
            return _poison(result, fault.data)
        raise ValueError(f"unknown fault mode {mode}")

    @property
    def faults_fired(self) -> int:
        return sum(c["fault"] is not None for c in self.calls)


def tool(fn: Callable) -> Callable:
    """Make a tool observable and fault-injectable by the lab."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        box = current_toolbox.get()
        if box is None:
            return fn(*args, **kwargs)
        return box.invoke(fn.__name__, fn, *args, **kwargs)

    return wrapper
