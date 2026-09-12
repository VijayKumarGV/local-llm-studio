"""Append-only audit log."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from backend import audit_log

TEST_TOKEN = "audit-test-token"


# ─── module-level roundtrips ───────────────────────────────────────────


class TestRecord:
    def test_write_and_list(self, fresh_schema: str) -> None:
        rid = audit_log.record("test_action", resource_type="thing", resource_id="abc", details={"k": "v"})
        assert isinstance(rid, str) and len(rid) >= 32
        entries = audit_log.list_recent()
        assert len(entries) == 1
        e = entries[0]
        assert e["action"] == "test_action"
        assert e["resource_type"] == "thing"
        assert e["resource_id"] == "abc"
        assert e["details"] == {"k": "v"}

    def test_details_defaults_to_empty_dict(self, fresh_schema: str) -> None:
        audit_log.record("empty_details_action")
        e = audit_log.list_recent()[0]
        assert e["details"] == {}

    def test_details_cap_prevents_giant_blobs(self, fresh_schema: str) -> None:
        # Serialized payload capped at 8000 chars
        huge = {"blob": "x" * 20_000}
        audit_log.record("giant_payload", details=huge)
        e = audit_log.list_recent()[0]
        # Truncation may make the JSON unparseable; list_recent falls back to {}
        assert isinstance(e["details"], dict)

    def test_never_raises_on_bad_input(self, fresh_schema: str) -> None:
        class Weird:
            def __repr__(self) -> str:  # non-JSON-serializable
                raise RuntimeError("boom")

        # Should not raise — audit_log swallows to avoid breaking real requests
        try:
            audit_log.record("noisy", details={"x": Weird()})
        except Exception as e:
            pytest.fail(f"audit_log.record raised: {e}")

    def test_list_ordering_newest_first(self, fresh_schema: str) -> None:
        for i in range(5):
            audit_log.record("act", resource_id=str(i))
        entries = audit_log.list_recent()
        assert [e["resource_id"] for e in entries] == ["4", "3", "2", "1", "0"]

    def test_filter_by_action(self, fresh_schema: str) -> None:
        audit_log.record("upload", resource_id="a")
        audit_log.record("delete", resource_id="b")
        audit_log.record("upload", resource_id="c")
        uploads = audit_log.list_recent(action="upload")
        assert {e["resource_id"] for e in uploads} == {"a", "c"}

    def test_filter_by_resource_type(self, fresh_schema: str) -> None:
        audit_log.record("touch", resource_type="file", resource_id="1")
        audit_log.record("touch", resource_type="message", resource_id="2")
        files = audit_log.list_recent(resource_type="file")
        assert len(files) == 1 and files[0]["resource_id"] == "1"

    def test_count(self, fresh_schema: str) -> None:
        for _ in range(3):
            audit_log.record("a")
        for _ in range(2):
            audit_log.record("b")
        assert audit_log.count() == 5
        assert audit_log.count(action="a") == 3


# ─── endpoint-level: writes are audited automatically ─────────────────


@pytest.fixture
def client(fresh_schema: str, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    fake = AsyncMock()

    async def _get(url, timeout=None, **kwargs):
        r = AsyncMock()
        r.raise_for_status = lambda: None
        r.json = lambda: {"models": []}
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


class TestEndpointInstrumentation:
    def test_project_delete_writes_audit_row(self, client: TestClient) -> None:
        pid = client.post("/api/projects", json={"name": "AuditMe"}).json()["project"]["id"]
        client.delete(f"/api/projects/{pid}")
        rows = audit_log.list_recent(action="delete", resource_type="project")
        assert any(r["resource_id"] == pid for r in rows)

    def test_conversation_delete_writes_audit_row(self, client: TestClient) -> None:
        pid = client.post("/api/projects", json={"name": "P"}).json()["project"]["id"]
        cid = client.post("/api/conversations", json={"project_id": pid}).json()["conversation"]["id"]
        client.delete(f"/api/conversations/{cid}")
        rows = audit_log.list_recent(action="delete", resource_type="conversation")
        assert any(r["resource_id"] == cid for r in rows)

    def test_sandbox_run_writes_audit_row(self, client: TestClient) -> None:
        client.post("/api/sandbox/run", json={"code": "print(1)"})
        rows = audit_log.list_recent(action="sandbox_run")
        assert len(rows) == 1
        assert rows[0]["details"]["code_chars"] == len("print(1)")
        assert "sandbox_kind" in rows[0]["details"]

    def test_audit_endpoint_returns_recent(self, client: TestClient) -> None:
        client.post("/api/sandbox/run", json={"code": "print(2)"})
        r = client.get("/api/audit?limit=5")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "success"
        assert data["count"] >= 1

    def test_audit_endpoint_filters(self, client: TestClient) -> None:
        client.post("/api/sandbox/run", json={"code": "print(3)"})
        r = client.get("/api/audit?action=sandbox_run")
        assert r.status_code == 200
        entries = r.json()["entries"]
        assert all(e["action"] == "sandbox_run" for e in entries)
