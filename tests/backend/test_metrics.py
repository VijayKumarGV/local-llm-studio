"""Prometheus metrics + /metrics exposition tests.

prometheus_client keeps a process-global registry, so incrementing a
Counter in one test leaks into the next. We test observable behavior
(delta before/after, endpoint response) rather than absolute values,
and use REGISTRY.collect() snapshots for value assertions.
"""

from __future__ import annotations

import prometheus_client
import pytest
from fastapi.testclient import TestClient

from backend import metrics


def _sample_value(sample_name: str, **label_match: str) -> float:
    """Look up a specific labelled sample from the shared registry. Match on
    the fully-qualified sample name (e.g. `studio_chat_requests_total`,
    `studio_retrieval_latency_seconds_count`) since a Counter's family is
    `studio_chat_requests` but its sample is suffixed `_total`."""
    for family in prometheus_client.REGISTRY.collect():
        for sample in family.samples:
            if sample.name != sample_name:
                continue
            if all(sample.labels.get(k) == v for k, v in label_match.items()):
                return sample.value
    return 0.0


class TestRecordHelpers:
    def test_chat_request_counter_increments(self) -> None:
        before = _sample_value("studio_chat_requests_total", model="m", status="success")
        metrics.record_chat_request("m", "success")
        after = _sample_value("studio_chat_requests_total", model="m", status="success")
        assert after == pytest.approx(before + 1)

    def test_tool_call_counter_increments(self) -> None:
        before = _sample_value("studio_tool_calls_total", tool="t", status="success")
        metrics.record_tool_call("t", "success")
        after = _sample_value("studio_tool_calls_total", tool="t", status="success")
        assert after == pytest.approx(before + 1)

    def test_feedback_relabels_ratings(self) -> None:
        before_up = _sample_value("studio_feedback_total", rating="up")
        before_down = _sample_value("studio_feedback_total", rating="down")
        before_clear = _sample_value("studio_feedback_total", rating="clear")
        metrics.record_feedback(1)
        metrics.record_feedback(-1)
        metrics.record_feedback(0)
        assert _sample_value("studio_feedback_total", rating="up") == pytest.approx(before_up + 1)
        assert _sample_value("studio_feedback_total", rating="down") == pytest.approx(before_down + 1)
        assert _sample_value("studio_feedback_total", rating="clear") == pytest.approx(before_clear + 1)

    def test_tokens_counter_ignores_zero(self) -> None:
        before = _sample_value("studio_tokens_total", model="m", kind="prompt")
        metrics.record_tokens("m", prompt_tokens=0)
        assert _sample_value("studio_tokens_total", model="m", kind="prompt") == pytest.approx(before)
        metrics.record_tokens("m", prompt_tokens=42)
        assert _sample_value("studio_tokens_total", model="m", kind="prompt") == pytest.approx(before + 42)


class TestActiveStreamsGauge:
    def test_inc_dec_balanced(self) -> None:
        start = _sample_value("studio_active_streams")
        with metrics.track_stream():
            assert _sample_value("studio_active_streams") == pytest.approx(start + 1)
        assert _sample_value("studio_active_streams") == pytest.approx(start)

    def test_gauge_decrements_even_on_exception(self) -> None:
        start = _sample_value("studio_active_streams")
        with pytest.raises(RuntimeError), metrics.track_stream():
            raise RuntimeError("simulated")
        assert _sample_value("studio_active_streams") == pytest.approx(start)


class TestRetrievalTimer:
    def test_observation_recorded(self) -> None:
        # Histogram `_count` sample surfaces the observation count.
        before = _sample_value("studio_retrieval_latency_seconds_count")
        with metrics.time_retrieval():
            pass
        assert _sample_value("studio_retrieval_latency_seconds_count") == pytest.approx(before + 1)


class TestMetricsEndpoint:
    def test_exposition_endpoint_returns_prometheus_text(self, fresh_schema: str) -> None:
        # Bootstrapping the app is expensive but the fixture already handles it.
        from backend.server import app

        client = TestClient(app)
        r = client.get("/metrics")
        assert r.status_code == 200
        assert "text/plain" in r.headers["content-type"]
        # Well-known base metric added by the Instrumentator's default set.
        assert "http_request_duration_highr_seconds" in r.text or "http_requests_total" in r.text

    def test_metrics_endpoint_excluded_from_openapi(self) -> None:
        from backend.server import app

        client = TestClient(app)
        openapi = client.get("/openapi.json").json()
        assert "/metrics" not in openapi.get("paths", {})
