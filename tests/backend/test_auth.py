"""Bearer-token auth middleware + /auth bootstrap endpoint."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

TEST_TOKEN = "auth-test-token-xyz"


@pytest.fixture
def authed_app(fresh_schema: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Return the app + a client with auth env set."""
    monkeypatch.setenv("SESSION_TOKEN", TEST_TOKEN)
    monkeypatch.setenv("STUDIO_TOKEN_FILE", str(tmp_path / "token"))
    from backend import auth as auth_module

    auth_module.reset_token_cache()

    fake = AsyncMock()

    async def _get(url, timeout=None, **kwargs):
        r = AsyncMock()
        r.raise_for_status = lambda: None
        r.json = lambda: {"models": []} if url == "/api/tags" else {}
        return r

    fake.get = _get
    monkeypatch.setattr("backend.ollama_client.get_ollama_client", lambda: fake)
    monkeypatch.setattr("backend.server.get_ollama_client", lambda: fake)
    from backend.server import app

    return app


@pytest.fixture
def client_authed(authed_app):
    with TestClient(authed_app, headers={"Authorization": f"Bearer {TEST_TOKEN}"}) as c:
        yield c


@pytest.fixture
def client_no_auth(authed_app):
    with TestClient(authed_app) as c:
        yield c


# ─── public endpoints skip auth ────────────────────────────────────────


def test_health_is_public(client_no_auth: TestClient) -> None:
    r = client_no_auth.get("/api/health")
    assert r.status_code == 200


def test_index_is_public(client_no_auth: TestClient) -> None:
    r = client_no_auth.get("/")
    assert r.status_code == 200
    assert "<html" in r.text.lower()


# ─── protected endpoints require auth ──────────────────────────────────


def test_projects_requires_auth(client_no_auth: TestClient) -> None:
    r = client_no_auth.get("/api/projects")
    assert r.status_code == 401
    body = r.json()
    assert body["error"] == "unauthorized"
    assert "GET /auth?token=" in body["hint"]


def test_projects_accepts_bearer_token(client_authed: TestClient) -> None:
    r = client_authed.get("/api/projects")
    assert r.status_code == 200


def test_wrong_bearer_token_is_401(client_no_auth: TestClient) -> None:
    r = client_no_auth.get("/api/projects", headers={"Authorization": "Bearer wrong-token"})
    assert r.status_code == 401


def test_cookie_auth_works(client_no_auth: TestClient) -> None:
    client_no_auth.cookies.set("studio_token", TEST_TOKEN)
    r = client_no_auth.get("/api/projects")
    assert r.status_code == 200


def test_wrong_cookie_is_401(client_no_auth: TestClient) -> None:
    client_no_auth.cookies.set("studio_token", "wrong-token")
    r = client_no_auth.get("/api/projects")
    assert r.status_code == 401


# ─── /auth bootstrap endpoint ──────────────────────────────────────────


def test_auth_bootstrap_sets_cookie(client_no_auth: TestClient) -> None:
    r = client_no_auth.get(f"/auth?token={TEST_TOKEN}", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/"
    # cookie set — follow-up request without explicit token succeeds
    r2 = client_no_auth.get("/api/projects")
    assert r2.status_code == 200


def test_auth_bootstrap_rejects_wrong_token(client_no_auth: TestClient) -> None:
    r = client_no_auth.get("/auth?token=obviously-wrong", follow_redirects=False)
    assert r.status_code == 401


# ─── token loader ──────────────────────────────────────────────────────


def test_env_var_beats_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from backend import auth

    tokfile = tmp_path / "token"
    tokfile.write_text("from-file-should-lose")
    monkeypatch.setenv("SESSION_TOKEN", "from-env-wins")
    monkeypatch.setenv("STUDIO_TOKEN_FILE", str(tokfile))
    auth.reset_token_cache()
    assert auth.load_or_create_token() == "from-env-wins"


def test_file_used_when_no_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from backend import auth

    tokfile = tmp_path / "token"
    tokfile.write_text("stored-token")
    monkeypatch.delenv("SESSION_TOKEN", raising=False)
    monkeypatch.setenv("STUDIO_TOKEN_FILE", str(tokfile))
    auth.reset_token_cache()
    assert auth.load_or_create_token() == "stored-token"


def test_auto_generate_on_first_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from backend import auth

    tokfile = tmp_path / "token"
    monkeypatch.delenv("SESSION_TOKEN", raising=False)
    monkeypatch.setenv("STUDIO_TOKEN_FILE", str(tokfile))
    auth.reset_token_cache()
    tok = auth.load_or_create_token()
    assert len(tok) >= 32
    assert tokfile.exists()
    assert tokfile.read_text().strip() == tok
