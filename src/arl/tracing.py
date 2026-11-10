"""Trace capture.

Spans are always recorded on the RunResult (and stored in SQLite). When
OpenTelemetry is configured, the same spans are also exported, so Langfuse
or any OTLP backend can receive them:

    arl run ... --otel console
    OTEL_EXPORTER_OTLP_ENDPOINT=https://cloud.langfuse.com/api/public/otel arl run ... --otel otlp
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

_otel_tracer = None


def setup_otel(mode: str | None) -> None:
    """mode: None (off), "console", or "otlp" (reads OTEL_EXPORTER_OTLP_* env vars)."""
    global _otel_tracer
    if not mode:
        _otel_tracer = None
        return
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

    if mode == "console":
        exporter = ConsoleSpanExporter()
    elif mode == "otlp":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter()
    else:
        raise ValueError(f"unknown otel mode {mode!r}")
    provider = TracerProvider(resource=Resource.create({"service.name": "agent-reliability-lab"}))
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _otel_tracer = trace.get_tracer("arl")


def shutdown_otel() -> None:
    if _otel_tracer is not None:
        from opentelemetry import trace

        trace.get_tracer_provider().shutdown()


class Trace:
    """Collects spans for one scenario run."""

    def __init__(self) -> None:
        self.spans: list[dict] = []

    @contextmanager
    def span(self, name: str, **attrs) -> Iterator[dict]:
        record = {"name": name, "attrs": dict(attrs), "start": time.time()}
        otel_cm = _otel_tracer.start_as_current_span(name, attributes=attrs) if _otel_tracer else None
        otel_span = otel_cm.__enter__() if otel_cm else None
        try:
            yield record
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            record["end"] = time.time()
            record["duration_s"] = record["end"] - record["start"]
            if otel_span is not None:
                for k, v in record["attrs"].items():
                    otel_span.set_attribute(k, v)
                otel_cm.__exit__(None, None, None)
            self.spans.append(record)
