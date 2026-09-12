"""Rate-limit middleware — verifies 429 fires when the per-endpoint budget
is exhausted.

We shrink the sandbox budget via env var so the test is fast (default is
30/min — too many requests). Env is scoped to the test via monkeypatch.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

TEST_TOKEN = "rate-limit-test"


@pytest.fixture
def client_with_tight_sandbox(fresh_schema: str, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # Rate limits are read at import time by slowapi decorators, so we
    # need to set env BEFORE the server module is imported. tests already
    # import server elsewhere, so we monkey-patch the module constant too
    # and rebuild the app to attach a fresh limiter.
    monkeypatch.setenv("SESSION_TOKEN", TEST_TOKEN)
    monkeypatch.setenv("STUDIO_RATE_LIMIT_SANDBOX", "3/minute")

    fake = AsyncMock()

    async def _get(url, timeout=None, **kwargs):
        r = AsyncMock()
        r.raise_for_status = lambda: None
        r.json = lambda: {"models": []}
        return r

    fake.get = _get
    monkeypatch.setattr("backend.ollama_client.get_ollama_client", lambda: fake)
    monkeypatch.setattr("backend.server.get_ollama_client", lambda: fake)

    from backend import auth as auth_module

    auth_module.reset_token_cache()

    # Reload rate_limit module + server module so they pick up the tighter env.
    import importlib

    from backend import rate_limit

    importlib.reload(rate_limit)
    from backend import server as server_module

    importlib.reload(server_module)

    with TestClient(server_module.app, headers={"Authorization": f"Bearer {TEST_TOKEN}"}) as c:
        yield c


def test_sandbox_429_after_budget_exhausted(client_with_tight_sandbox: TestClient) -> None:
    payload = {"code": "print(1)"}
    # Budget is 3/minute — first 3 must succeed, 4th must be throttled.
    statuses = []
    for _ in range(5):
        r = client_with_tight_sandbox.post("/api/sandbox/run", json=payload)
        statuses.append(r.status_code)
    assert 200 in statuses
    assert 429 in statuses, f"expected 429 in {statuses}"


def test_untight_endpoints_stay_open(client_with_tight_sandbox: TestClient) -> None:
    # A high-limit endpoint (health) shouldn't be throttled at 5 hits.
    for _ in range(10):
        r = client_with_tight_sandbox.get("/api/health")
        assert r.status_code == 200
