"""
Prometheus metrics for Local LLM Studio.

Exposition
----------
`instrument(app)` mounts a `/metrics` endpoint that Prometheus can
scrape. Base HTTP-request metrics come from
`prometheus_fastapi_instrumentator`; the custom domain metrics below are
incremented from the orchestrator, RAG layer, and feedback path.

Metric taxonomy — every name is prefixed `studio_` so a shared
Prometheus can host multiple projects without collisions.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Iterator
from typing import Any

from prometheus_client import Counter, Gauge, Histogram

# ── Chat requests ──────────────────────────────────────────────────────
chat_requests_total = Counter(
    "studio_chat_requests_total",
    "Chat requests by model and terminal status.",
    ["model", "status"],  # status ∈ success | error | cancelled
)

active_streams = Gauge(
    "studio_active_streams",
    "Currently-streaming chat requests.",
)

ollama_up = Gauge(
    "studio_ollama_up",
    "1 if /api/health last saw ollama return 2xx, else 0.",
)

# ── Retrieval (RAG) ────────────────────────────────────────────────────
retrieval_latency_seconds = Histogram(
    "studio_retrieval_latency_seconds",
    "End-to-end RAG retrieve() latency.",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)

retrieval_hits = Histogram(
    "studio_retrieval_hits",
    "Number of RAG hits returned (0 = empty).",
    buckets=(0, 1, 2, 4, 6, 8, 12, 20),
)

# ── Tool calls ────────────────────────────────────────────────────────
tool_calls_total = Counter(
    "studio_tool_calls_total",
    "Tool invocations by name + terminal status.",
    ["tool", "status"],  # status ∈ success | error | denied | timeout
)

# ── Feedback ──────────────────────────────────────────────────────────
feedback_total = Counter(
    "studio_feedback_total",
    "Feedback events by rating.",
    ["rating"],  # rating ∈ up | down | clear
)

# ── Token usage ───────────────────────────────────────────────────────
tokens_total = Counter(
    "studio_tokens_total",
    "Cumulative token counts by model + role.",
    ["model", "kind"],  # kind ∈ prompt | completion
)


# ── Convenience helpers ───────────────────────────────────────────────


@contextlib.contextmanager
def track_stream() -> Iterator[None]:
    """Bump the active-streams gauge for the duration of a chat stream.

    Always decrements on exit — even if the generator was cancelled or
    raised — so the gauge can never leak upward.
    """
    active_streams.inc()
    try:
        yield
    finally:
        active_streams.dec()


@contextlib.contextmanager
def time_retrieval() -> Iterator[None]:
    """Record retrieval latency into the histogram."""
    started = time.perf_counter()
    try:
        yield
    finally:
        retrieval_latency_seconds.observe(time.perf_counter() - started)


def record_chat_request(model: str, status: str) -> None:
    chat_requests_total.labels(model=model or "unknown", status=status).inc()


def record_tool_call(tool: str, status: str) -> None:
    tool_calls_total.labels(tool=tool or "unknown", status=status).inc()


def record_feedback(rating: int) -> None:
    """Rating is -1 / 0 / +1; we relabel to (down | clear | up)."""
    label = "up" if rating > 0 else "down" if rating < 0 else "clear"
    feedback_total.labels(rating=label).inc()


def record_tokens(model: str, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
    """Bump the prompt / completion counters. Zero values are a no-op."""
    if prompt_tokens:
        tokens_total.labels(model=model or "unknown", kind="prompt").inc(prompt_tokens)
    if completion_tokens:
        tokens_total.labels(model=model or "unknown", kind="completion").inc(completion_tokens)


def record_retrieval_hits(n: int) -> None:
    retrieval_hits.observe(max(0, n))


# ── FastAPI wiring ────────────────────────────────────────────────────


def instrument(app: Any) -> None:
    """Mount /metrics and register the base HTTP request instrumentation.

    Idempotent: safe to call twice (the instrumentator dedupes).
    """
    from prometheus_fastapi_instrumentator import Instrumentator

    # `should_group_status_codes=False` keeps 404 vs 401 separate — matters
    # for our auth-middleware dashboards. `excluded_handlers` excludes the
    # health probe from p95 charts (otherwise it dominates volume).
    (
        Instrumentator(
            should_group_status_codes=False,
            excluded_handlers=["/api/health", "/metrics"],
        )
        .instrument(app)
        .expose(app, endpoint="/metrics", include_in_schema=False, tags=["monitoring"])
    )
