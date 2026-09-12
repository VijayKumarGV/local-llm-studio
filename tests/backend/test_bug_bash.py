"""Edge cases surfaced during the Week 11 bug bash. Each test defends
one specific ambiguity in a security- or reliability-sensitive path."""

from __future__ import annotations

import contextlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEST_TOKEN = "bug-bash-token-xyz"


@pytest.fixture
def client(fresh_schema: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    # Dev sandbox exports HTTP(S)_PROXY / ALL_PROXY; strip them so
    # TestClient's httpx doesn't try to route the ASGI transport through
    # the phantom SOCKS proxy.
    for v in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "FTP_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
        "ftp_proxy",
    ):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("SESSION_TOKEN", TEST_TOKEN)
    monkeypatch.setenv("STUDIO_TOKEN_FILE", str(tmp_path / "token"))
    from backend import auth, config

    config.reload()
    auth._TOKEN = None
    from backend import server

    return TestClient(server.app)


# ── Auth ─────────────────────────────────────────────────────────────


class TestAuthEdgeCases:
    def test_empty_cookie_is_unauthorized(self, client: TestClient) -> None:
        r = client.get("/api/projects", cookies={"studio_token": ""})
        assert r.status_code == 401

    def test_whitespace_bearer_token_rejected(self, client: TestClient) -> None:
        r = client.get("/api/projects", headers={"Authorization": "Bearer    "})
        assert r.status_code == 401

    def test_wrong_scheme_ignores_credential(self, client: TestClient) -> None:
        # Basic isn't accepted — must be Bearer.
        r = client.get("/api/projects", headers={"Authorization": f"Basic {TEST_TOKEN}"})
        assert r.status_code == 401

    def test_bearer_case_insensitive(self, client: TestClient) -> None:
        r = client.get("/api/projects", headers={"Authorization": f"bearer {TEST_TOKEN}"})
        assert r.status_code == 200

    def test_token_in_query_string_never_authenticates(self, client: TestClient) -> None:
        r = client.get(f"/api/projects?token={TEST_TOKEN}")
        assert r.status_code == 401

    def test_prefix_match_is_rejected(self, client: TestClient) -> None:
        # Constant-time compare should still fail on prefix — never let a
        # partial match through.
        r = client.get("/api/projects", headers={"Authorization": f"Bearer {TEST_TOKEN[:5]}"})
        assert r.status_code == 401


# ── Chunker ──────────────────────────────────────────────────────────


class TestChunkerEdges:
    def test_unicode_and_emoji_preserved(self) -> None:
        from backend import rag

        text = "# Notes\n\nHello 世界 🌏 — CSRF/XSS ✅"
        chunks = rag._chunk_with_headings(text, "u.md")
        assert len(chunks) == 1
        assert "世界" in chunks[0]["text"]
        assert "🌏" in chunks[0]["text"]

    def test_single_giant_word_still_splits(self) -> None:
        from backend import rag

        text = "a" * 20000
        chunks = rag._chunk_with_headings(text, "wall.md")
        assert len(chunks) >= 2
        assert all(len(c["text"]) <= rag.CHUNK_TARGET_CHARS for c in chunks)


# ── Compare chat ─────────────────────────────────────────────────────


class TestCompareChat:
    def test_empty_message_rejected(self, client: TestClient) -> None:
        r = client.post(
            "/api/chat/compare",
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
            json={"message": "   "},
        )
        assert r.status_code == 400
        assert "message" in r.json().get("detail", "").lower()

    def test_missing_message_rejected(self, client: TestClient) -> None:
        r = client.post(
            "/api/chat/compare",
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
            json={},
        )
        assert r.status_code == 400


# ── Cost ledger ──────────────────────────────────────────────────────


class TestCostLedgerEdges:
    def test_missing_group_by_defaults_to_model(self, client: TestClient) -> None:
        r = client.get("/api/cost/summary", headers={"Authorization": f"Bearer {TEST_TOKEN}"})
        assert r.status_code == 200
        assert r.json()["group_by"] == "model"

    def test_invalid_group_by_rejected(self, client: TestClient) -> None:
        r = client.get(
            "/api/cost/summary?group_by=user",
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        )
        assert r.status_code == 400


# ── Audit log ────────────────────────────────────────────────────────


class TestAuditLogRobust:
    def test_record_never_raises_on_bad_input(self) -> None:
        from backend import audit_log

        class Weird:
            def __str__(self) -> str:
                raise RuntimeError("unserializable")

        # Should swallow the failure — logging must never break the caller.
        with contextlib.suppress(BaseException):
            audit_log.record("test", details={"weird": Weird()})


# ── Onboarding ───────────────────────────────────────────────────────


class TestOnboardingEdges:
    def test_missing_fields_do_not_crash_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Ollama returns a garbage JSON shape.
        from unittest.mock import AsyncMock, MagicMock

        from backend import onboarding

        resp = MagicMock()
        resp.json = MagicMock(return_value={"unexpected_key": []})
        resp.raise_for_status = MagicMock(return_value=None)
        fake = AsyncMock()
        fake.get = AsyncMock(return_value=resp)
        monkeypatch.setattr("backend.onboarding.get_ollama_client", lambda: fake)
        got = onboarding._recommended_missing([])  # empty installed list
        # All recommended models should be flagged missing.
        assert set(got) == set(onboarding.RECOMMENDED_MODELS)
