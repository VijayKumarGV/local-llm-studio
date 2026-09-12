"""request-id middleware behavior."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(fresh_schema: str, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from unittest.mock import AsyncMock

    fake = AsyncMock()

    async def _get(url, timeout=None, **kwargs):
        r = AsyncMock()
        r.raise_for_status = lambda: None
        r.json = lambda: {"models": []} if url == "/api/tags" else {}
        return r

    fake.get = _get
    monkeypatch.setattr("backend.ollama_client.get_ollama_client", lambda: fake)

    from backend.server import app

    with TestClient(app) as c:
        yield c


UUID_LIKE = re.compile(r"^[a-f0-9-]{6,64}$")


def test_response_carries_request_id_header(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    rid = r.headers.get("X-Request-ID")
    assert rid is not None
    assert UUID_LIKE.match(rid)


def test_client_supplied_request_id_echoed(client: TestClient) -> None:
    r = client.get("/api/health", headers={"X-Request-ID": "test-abc-123"})
    assert r.status_code == 200
    assert r.headers.get("X-Request-ID") == "test-abc-123"


def test_each_request_gets_unique_id(client: TestClient) -> None:
    ids = {client.get("/api/health").headers["X-Request-ID"] for _ in range(5)}
    assert len(ids) == 5


def test_request_id_var_default_when_no_request() -> None:
    from backend.middleware import request_id_var

    assert request_id_var.get() == "-"
