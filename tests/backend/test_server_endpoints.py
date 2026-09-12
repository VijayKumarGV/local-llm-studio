"""Integration tests for the FastAPI endpoints.

Uses FastAPI's TestClient — synchronous, but runs the app's lifespan hooks.
DB is isolated per-test via the `fresh_schema` fixture. Ollama-backed
endpoints (`/api/health`, `/api/models`, `/api/memory/extract`, `/api/chat/*`,
`/api/rag/query`) are mocked so tests don't require a running model.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

TEST_TOKEN = "test-token-abc-123"


@pytest.fixture
def client(fresh_schema: str, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # Patch the shared Ollama client BEFORE the app's lifespan hook runs, so
    # /api/health and friends see the mock immediately.
    fake = AsyncMock()

    async def _get(url, timeout=None, **kwargs):
        r = AsyncMock()
        r.raise_for_status = lambda: None
        if url == "/api/tags":
            r.json = lambda: {
                "models": [
                    {"name": "qwen2.5:32b"},
                    {"name": "llama3.2:1b"},
                    {"name": "nomic-embed-text:latest"},
                ]
            }
        else:
            r.json = lambda: {}
        return r

    fake.get = _get
    # server.py binds `get_ollama_client` at import time — patching the
    # source module isn't enough, we also need the local reference.
    monkeypatch.setattr("backend.ollama_client.get_ollama_client", lambda: fake)
    monkeypatch.setattr("backend.server.get_ollama_client", lambda: fake)

    # Auth: fix the token to a known value and reset the module cache so
    # load_or_create_token sees the env var.
    monkeypatch.setenv("SESSION_TOKEN", TEST_TOKEN)
    from backend import auth as auth_module

    auth_module.reset_token_cache()

    from backend.server import app

    with TestClient(app, headers={"Authorization": f"Bearer {TEST_TOKEN}"}) as c:
        yield c


# ─── health + models ─────────────────────────────────────────────────────


def test_health_ok(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] in ("ok", "degraded")
    assert data["ollama"]["up"] is True
    assert data["ollama"]["models"] == 3
    assert "db_path" in data


def test_models_list(client: TestClient) -> None:
    r = client.get("/api/models")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "success"
    names = {m["name"] for m in data["models"]}
    assert "qwen2.5:32b" in names
    # Every model row must have capabilities attached
    assert all("capabilities" in m for m in data["models"])


# ─── projects CRUD ───────────────────────────────────────────────────────


def test_project_create_list_get(client: TestClient) -> None:
    r = client.post("/api/projects", json={"name": "TestProj", "icon": "🛠️"})
    assert r.status_code == 200
    pid = r.json()["project"]["id"]

    r = client.get("/api/projects")
    assert any(p["id"] == pid for p in r.json()["projects"])

    r = client.get(f"/api/projects/{pid}")
    assert r.status_code == 200
    assert r.json()["project"]["name"] == "TestProj"


def test_project_patch(client: TestClient) -> None:
    pid = client.post("/api/projects", json={"name": "P"}).json()["project"]["id"]
    r = client.patch(f"/api/projects/{pid}", json={"description": "Updated", "pinned": 1})
    assert r.status_code == 200
    assert r.json()["project"]["description"] == "Updated"
    assert r.json()["project"]["pinned"] == 1


def test_project_delete(client: TestClient) -> None:
    pid = client.post("/api/projects", json={"name": "P"}).json()["project"]["id"]
    r = client.delete(f"/api/projects/{pid}")
    assert r.status_code == 200
    r = client.get(f"/api/projects/{pid}")
    assert r.status_code == 404


def test_project_get_missing_404(client: TestClient) -> None:
    r = client.get("/api/projects/nonexistent")
    assert r.status_code == 404


# ─── conversations CRUD ───────────────────────────────────────────────────


def test_conversation_lifecycle(client: TestClient) -> None:
    pid = client.post("/api/projects", json={"name": "P"}).json()["project"]["id"]
    conv = client.post("/api/conversations", json={"project_id": pid, "title": "Chat"}).json()["conversation"]
    cid = conv["id"]

    # Patch
    client.patch(f"/api/conversations/{cid}", json={"title": "Renamed"})
    got = client.get(f"/api/conversations/{cid}").json()["conversation"]
    assert got["title"] == "Renamed"

    # List filtered by project
    listing = client.get(f"/api/conversations?project_id={pid}").json()["conversations"]
    assert any(c["id"] == cid for c in listing)

    # Archive + list excludes archived by default
    client.patch(f"/api/conversations/{cid}", json={"archived": 1})
    listing = client.get(f"/api/conversations?project_id={pid}").json()["conversations"]
    assert not any(c["id"] == cid for c in listing)
    listing = client.get(f"/api/conversations?project_id={pid}&include_archived=true").json()["conversations"]
    assert any(c["id"] == cid for c in listing)

    # Delete
    client.delete(f"/api/conversations/{cid}")
    assert client.get(f"/api/conversations/{cid}").status_code == 404


def test_conversation_duplicate(client: TestClient) -> None:
    pid = client.post("/api/projects", json={"name": "P"}).json()["project"]["id"]
    cid = client.post("/api/conversations", json={"project_id": pid}).json()["conversation"]["id"]

    r = client.post(f"/api/conversations/{cid}/duplicate")
    assert r.status_code == 200
    dup_id = r.json()["conversation"]["id"]
    assert dup_id != cid


def test_conversation_branch(client: TestClient) -> None:
    from backend import database

    pid = client.post("/api/projects", json={"name": "P"}).json()["project"]["id"]
    cid = client.post("/api/conversations", json={"project_id": pid}).json()["conversation"]["id"]
    # Seed 3 messages so we have a branch point
    database.add_message(cid, "user", "q1")
    database.add_message(cid, "assistant", "a1")
    branch_pt = database.add_message(cid, "user", "q2")

    r = client.post(f"/api/conversations/{cid}/branch", json={"message_id": branch_pt["id"]})
    assert r.status_code == 200
    branch_id = r.json()["conversation"]["id"]
    branch_msgs = client.get(f"/api/conversations/{branch_id}").json()["conversation"]["messages"]
    # Branched conv should end exactly at (and include) the branch-point message
    assert branch_msgs[-1]["content"] == "q2"
    assert len(branch_msgs) == 3


def test_branch_requires_message_id(client: TestClient) -> None:
    pid = client.post("/api/projects", json={"name": "P"}).json()["project"]["id"]
    cid = client.post("/api/conversations", json={"project_id": pid}).json()["conversation"]["id"]
    r = client.post(f"/api/conversations/{cid}/branch", json={})
    assert r.status_code == 400


# ─── messages ────────────────────────────────────────────────────────────


def test_message_delete(client: TestClient) -> None:
    from backend import database

    pid = client.post("/api/projects", json={"name": "P"}).json()["project"]["id"]
    cid = client.post("/api/conversations", json={"project_id": pid}).json()["conversation"]["id"]
    m = database.add_message(cid, "user", "hi")
    r = client.delete(f"/api/messages/{m['id']}")
    assert r.status_code == 200


# ─── settings ────────────────────────────────────────────────────────────


def test_settings_get_defaults(client: TestClient) -> None:
    r = client.get("/api/settings")
    assert r.status_code == 200
    settings = r.json()["settings"]
    assert "default_model" in settings
    assert "system_prompt" in settings


def test_settings_save_and_readback(client: TestClient) -> None:
    r = client.post("/api/settings", json={"default_model": "custom-model:latest"})
    assert r.status_code == 200
    r = client.get("/api/settings")
    assert r.json()["settings"]["default_model"] == "custom-model:latest"


# ─── search ──────────────────────────────────────────────────────────────


def test_search_across_content(client: TestClient) -> None:
    from backend import database

    pid = client.post("/api/projects", json={"name": "Searchable"}).json()["project"]["id"]
    cid = client.post("/api/conversations", json={"project_id": pid, "title": "Findable chat"}).json()["conversation"][
        "id"
    ]
    database.add_message(cid, "assistant", "This is a unique needle_xyz phrase we can find.")

    r = client.get("/api/search?q=needle_xyz")
    assert r.status_code == 200
    data = r.json()["results"]
    assert any("needle_xyz" in (m.get("content") or "") for m in data["messages"])


def test_search_empty_query(client: TestClient) -> None:
    r = client.get("/api/search?q=")
    assert r.status_code == 200
    r = r.json()["results"]
    assert r["messages"] == []
    assert r["conversations"] == []


# ─── feedback endpoint ──────────────────────────────────────────────────


def test_feedback_endpoint_roundtrip(client: TestClient) -> None:
    from backend import database

    pid = client.post("/api/projects", json={"name": "P"}).json()["project"]["id"]
    cid = client.post("/api/conversations", json={"project_id": pid}).json()["conversation"]["id"]
    m = database.add_message(cid, "assistant", "hi")

    r = client.post("/api/feedback", json={"message_id": m["id"], "rating": 1})
    assert r.status_code == 200

    r = client.get(f"/api/feedback?message_id={m['id']}")
    assert r.json()["feedback"]["rating"] == 1


def test_feedback_requires_message_id(client: TestClient) -> None:
    r = client.post("/api/feedback", json={"rating": 1})
    assert r.status_code == 400


def test_feedback_summary(client: TestClient) -> None:
    r = client.get("/api/feedback")
    assert r.status_code == 200
    assert "summary" in r.json()


# ─── memory endpoints ──────────────────────────────────────────────────


def test_memory_list_empty(client: TestClient) -> None:
    r = client.get("/api/memory")
    assert r.status_code == 200
    assert r.json()["memories"] == []


def test_memory_extract_requires_conversation_id(client: TestClient) -> None:
    r = client.post("/api/memory/extract", json={})
    assert r.status_code == 400


# ─── artifacts endpoint ────────────────────────────────────────────────


def test_artifacts_list_empty(client: TestClient) -> None:
    r = client.get("/api/artifacts")
    assert r.status_code == 200
    assert r.json()["artifacts"] == []


def test_artifact_get_missing_404(client: TestClient) -> None:
    r = client.get("/api/artifacts/nonexistent")
    assert r.status_code == 404


# ─── sandbox endpoint ──────────────────────────────────────────────────


def test_sandbox_run_hello_world(client: TestClient) -> None:
    r = client.post("/api/sandbox/run", json={"code": "print('hello')"})
    assert r.status_code == 200
    data = r.json()
    assert data["stdout"] == "hello"
    assert data["status"] == "success"


def test_sandbox_run_requires_code(client: TestClient) -> None:
    r = client.post("/api/sandbox/run", json={"code": ""})
    assert r.status_code == 400


def test_sandbox_timeout_enforced(client: TestClient) -> None:
    r = client.post(
        "/api/sandbox/run",
        json={"code": "import time; time.sleep(10)", "timeout": 1},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "timeout"


# ─── static / SPA root ─────────────────────────────────────────────────


def test_index_html_served(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "<html" in r.text.lower()
    # __ASSET_HASH__ token was substituted with a real hash
    assert "__ASSET_HASH__" not in r.text
