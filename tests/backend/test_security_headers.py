"""Security header middleware."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

TEST_TOKEN = "sh-test-token"


@pytest.fixture
def client(fresh_schema: str, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    fake = AsyncMock()

    async def _get(url, timeout=None, **kwargs):
        r = AsyncMock()
        r.raise_for_status = lambda: None
        r.json = lambda: {"models": []} if url == "/api/tags" else {}
        return r

    fake.get = _get
    monkeypatch.setattr("backend.ollama_client.get_ollama_client", lambda: fake)
    monkeypatch.setattr("backend.server.get_ollama_client", lambda: fake)
    monkeypatch.setenv("SESSION_TOKEN", TEST_TOKEN)
    from backend import auth as auth_module

    auth_module.reset_token_cache()

    from backend.server import app

    with TestClient(app, headers={"Authorization": f"Bearer {TEST_TOKEN}"}) as c:
        yield c


REQUIRED = (
    "content-security-policy",
    "x-content-type-options",
    "x-frame-options",
    "referrer-policy",
    "permissions-policy",
)


def test_headers_on_health(client: TestClient) -> None:
    r = client.get("/api/health")
    for h in REQUIRED:
        assert h in r.headers, f"missing {h}"


def test_headers_on_index(client: TestClient) -> None:
    r = client.get("/")
    for h in REQUIRED:
        assert h in r.headers


def test_headers_on_401(fresh_schema: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SESSION_TOKEN", TEST_TOKEN)
    from backend import auth as auth_module

    auth_module.reset_token_cache()
    from backend.server import app

    fake = AsyncMock()

    async def _get(url, timeout=None, **kwargs):
        r = AsyncMock()
        r.raise_for_status = lambda: None
        r.json = lambda: {"models": []}
        return r

    fake.get = _get
    monkeypatch.setattr("backend.ollama_client.get_ollama_client", lambda: fake)
    monkeypatch.setattr("backend.server.get_ollama_client", lambda: fake)

    with TestClient(app) as raw_client:  # no default auth header
        r = raw_client.get("/api/projects")
    assert r.status_code == 401
    for h in REQUIRED:
        assert h in r.headers, f"missing {h} on 401 response"


def test_csp_blocks_unsafe(client: TestClient) -> None:
    csp = client.get("/api/health").headers["content-security-policy"]
    assert "'unsafe-eval'" not in csp
    assert "frame-ancestors 'none'" in csp
    assert "default-src 'self'" in csp


def test_x_frame_options_deny(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.headers["x-frame-options"] == "DENY"


def test_x_content_type_options_nosniff(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
