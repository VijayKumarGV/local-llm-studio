"""OpenTelemetry setup tests.

We don't want to bring up a real OTLP collector, so these tests only
verify:
  - `enabled()` reads the env correctly
  - `setup()` is a no-op when disabled (no exporter registered, no crash)
  - `tracer()` always returns a Tracer (even before setup)
  - the SDK doesn't blow up on `setup()` when the endpoint is configured
    (we point it at an unreachable URL — the BatchSpanProcessor swallows
    connection failures asynchronously).
"""

from __future__ import annotations

import pytest

from backend import tracing


@pytest.fixture(autouse=True)
def _reset_tracing_state():
    """Fresh module state per test — otherwise the first setup call sticks
    and later `enabled` env changes are ignored."""
    tracing._reset_for_tests()
    yield
    tracing._reset_for_tests()


class TestEnabledFlag:
    def test_disabled_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        assert tracing.enabled() is False

    def test_enabled_when_endpoint_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
        assert tracing.enabled() is True


class TestSetup:
    def test_noop_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        tracing.setup()  # must not raise

    def test_idempotent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        tracing.setup()
        tracing.setup()  # second call is a no-op

    def test_configures_provider_when_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider

        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:59999")
        tracing.setup()
        provider = trace.get_tracer_provider()
        assert isinstance(provider, TracerProvider)
        # Shut down the batch exporter so it doesn't keep retrying the
        # unreachable localhost port in a background thread after the test
        # exits, dumping noise into other tests' output.
        provider.shutdown()


class TestTracer:
    def test_returns_tracer_before_setup(self) -> None:
        t = tracing.tracer()
        assert t is not None
        with t.start_as_current_span("test-span"):
            pass  # smoke: doesn't crash even without setup

    def test_start_span_is_safe_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        tracing.setup()
        with tracing.tracer().start_as_current_span("noop-span") as span:
            span.set_attribute("k", "v")  # NonRecordingSpan swallows this cleanly
