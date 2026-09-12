"""
OpenTelemetry tracing — opt-in via `OTEL_EXPORTER_OTLP_ENDPOINT`.

When the endpoint env var is unset, `setup()` is a no-op and `tracer()`
returns a no-op tracer, so the rest of the code can call
`with tracer().start_as_current_span(...)` unconditionally without
adding runtime overhead or requiring a collector to be running.

When it IS set, spans are exported via OTLP-HTTP (default endpoint on
`http://localhost:4318`) to whatever collector the operator has running
— we ship a Tempo container in `docker/observability-compose.yml`.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Tracer

log = logging.getLogger("studio.tracing")

SERVICE_NAME = "local-llm-studio"
_INITIALIZED = False


def _endpoint() -> str:
    """Return the configured OTLP endpoint, or '' if disabled."""
    return os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()


def enabled() -> bool:
    return bool(_endpoint())


def setup(app: Any | None = None) -> None:
    """Wire the SDK + FastAPI instrumentation. Idempotent + safe when
    tracing is disabled (returns without side effects)."""
    global _INITIALIZED
    if _INITIALIZED:
        return
    if not enabled():
        log.debug("tracing disabled: OTEL_EXPORTER_OTLP_ENDPOINT unset")
        _INITIALIZED = True
        return
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import SERVICE_NAME as SERVICE_NAME_KEY
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create({SERVICE_NAME_KEY: SERVICE_NAME})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)

    if app is not None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, excluded_urls="/api/health,/metrics")

    log.info("tracing enabled → %s", _endpoint())
    _INITIALIZED = True


def tracer() -> Tracer:
    """Return the studio's Tracer. Safe to call before or after setup —
    the default no-op provider stands in when tracing is disabled."""
    return trace.get_tracer(SERVICE_NAME)


def _reset_for_tests() -> None:
    """Test-only escape hatch to allow re-calling `setup` after env changes."""
    global _INITIALIZED
    _INITIALIZED = False
