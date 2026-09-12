"""Long-term memory: extraction JSON parsing + storage + recall."""

from __future__ import annotations

from unittest.mock import AsyncMock

import numpy as np
import pytest

from backend import database, long_term_memory as ltm


# ─── _parse_facts: pure parser, most surface area for LLM output shape ────

class TestParseFacts:
    def test_empty_input(self) -> None:
        assert ltm._parse_facts("") == []

    def test_array_of_objects(self) -> None:
        out = ltm._parse_facts('[{"fact": "a", "category": "x"}, {"fact": "b"}]')
        assert out == [
            {"fact": "a", "category": "x"},
            {"fact": "b", "category": "general"},
        ]

    def test_single_object(self) -> None:
        out = ltm._parse_facts('{"fact": "solo", "category": "user_profile"}')
        assert out == [{"fact": "solo", "category": "user_profile"}]

    def test_wrapping_object_with_facts_key(self) -> None:
        raw = '{"facts": [{"fact": "a"}, {"fact": "b"}]}'
        out = ltm._parse_facts(raw)
        assert len(out) == 2

    def test_wrapping_object_with_memories_key(self) -> None:
        out = ltm._parse_facts('{"memories": [{"fact": "m1"}]}')
        assert len(out) == 1 and out[0]["fact"] == "m1"

    def test_prose_wrapped_json(self) -> None:
        raw = 'Here are the facts:\n\n{"fact": "extracted", "category": "preference"}\n\nDone.'
        out = ltm._parse_facts(raw)
        assert out == [{"fact": "extracted", "category": "preference"}]

    def test_array_of_strings(self) -> None:
        # Some models return just strings instead of objects
        out = ltm._parse_facts('["fact one", "fact two"]')
        assert out == [
            {"fact": "fact one", "category": "general"},
            {"fact": "fact two", "category": "general"},
        ]

    def test_empty_array(self) -> None:
        assert ltm._parse_facts("[]") == []

    def test_garbage_returns_empty(self) -> None:
        assert ltm._parse_facts("this is not json at all") == []

    def test_malformed_json_returns_empty(self) -> None:
        assert ltm._parse_facts('{"fact": "unclosed') == []

    def test_caps_at_max_memories(self) -> None:
        facts = [{"fact": f"f{i}"} for i in range(50)]
        import json
        out = ltm._parse_facts(json.dumps(facts))
        assert len(out) == ltm.MAX_MEMORIES_PER_EXTRACTION

    def test_fact_text_truncated(self) -> None:
        raw = '[{"fact": "' + ("x" * 1000) + '"}]'
        out = ltm._parse_facts(raw)
        assert len(out[0]["fact"]) == 400  # per the 400-char cap


# ─── extract_from_conversation: needs mocked ollama + embed ────

@pytest.fixture
def conv_with_messages(fresh_schema: str) -> str:
    proj = database.create_project(name="P")
    conv = database.create_conversation(title="C", project_id=proj["id"])
    database.add_message(conv["id"], "user", "I'm building a Rust CLI called cargo-clip")
    database.add_message(conv["id"], "assistant", "Great — what should it do?")
    database.add_message(conv["id"], "user", "It should copy the last cargo build error to clipboard")
    return conv["id"]


@pytest.fixture
def fake_embed_batch(monkeypatch: pytest.MonkeyPatch):
    """Return deterministic 8-dim vectors — enough to test cosine ordering."""
    async def _fake(texts, model, batch_size=32):
        return [
            np.array([float(hash(t + str(i)) % 100) / 100 for i in range(8)], dtype=np.float32)
            for t in texts
        ]
    monkeypatch.setattr("backend.rag._embed_batch", _fake)
    monkeypatch.setattr("backend.long_term_memory._embed_batch", _fake)


class TestExtractFromConversation:
    @pytest.mark.asyncio
    async def test_missing_conversation(self, fresh_schema: str) -> None:
        r = await ltm.extract_from_conversation("does-not-exist")
        assert r["status"] == "error"

    @pytest.mark.asyncio
    async def test_conversation_too_short_is_empty(self, fresh_schema: str) -> None:
        proj = database.create_project(name="P")
        conv = database.create_conversation(title="C", project_id=proj["id"])
        database.add_message(conv["id"], "user", "hi")  # only 1 message
        r = await ltm.extract_from_conversation(conv["id"])
        assert r["status"] == "empty"

    @pytest.mark.asyncio
    async def test_successful_extraction(
        self, conv_with_messages: str, monkeypatch: pytest.MonkeyPatch, fake_embed_batch,
    ) -> None:
        # Mock the ollama chat call to return canned JSON
        async def _fake_post(url, json, timeout):
            assert url == "/api/chat"
            resp = AsyncMock()
            resp.raise_for_status = lambda: None
            resp.json = lambda: {
                "message": {"content": '{"facts": [{"fact": "user is building cargo-clip in Rust", "category": "project_state"}]}'},
            }
            return resp

        fake_client = AsyncMock()
        fake_client.post = _fake_post
        monkeypatch.setattr("backend.long_term_memory.get_ollama_client", lambda: fake_client)

        r = await ltm.extract_from_conversation(conv_with_messages)
        assert r["status"] == "success"
        assert r["extracted"] == 1
        assert "cargo-clip" in r["facts"][0]["fact"]

    @pytest.mark.asyncio
    async def test_replace_existing_wipes_prior(
        self, conv_with_messages: str, monkeypatch: pytest.MonkeyPatch, fake_embed_batch,
    ) -> None:
        async def _post(url, json, timeout):
            r = AsyncMock()
            r.raise_for_status = lambda: None
            r.json = lambda: {"message": {"content": '[{"fact": "batch A"}]'}}
            return r
        fake_client = AsyncMock()
        fake_client.post = _post
        monkeypatch.setattr("backend.long_term_memory.get_ollama_client", lambda: fake_client)

        await ltm.extract_from_conversation(conv_with_messages)
        assert len(ltm.list_memories()) == 1
        # Second call with replace_existing → still 1 (old row deleted)
        await ltm.extract_from_conversation(conv_with_messages, replace_existing=True)
        assert len(ltm.list_memories()) == 1


class TestRecall:
    @pytest.mark.asyncio
    async def test_empty_when_no_memories(self, fresh_schema: str, fake_embed_batch) -> None:
        hits = await ltm.recall("anything")
        assert hits == []

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self, fresh_schema: str) -> None:
        hits = await ltm.recall("")
        assert hits == []

    @pytest.mark.asyncio
    async def test_returns_stored_memories(
        self, fresh_schema: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Insert one memory manually with a known embedding, then query.
        import uuid
        from datetime import datetime
        vec_a = np.array([1.0] + [0.0] * 7, dtype=np.float32)
        with database.get_connection() as conn:
            conn.execute(
                "INSERT INTO long_term_memory (id, fact, category, project_id, source_conversation_id, "
                "embedding, embedding_model, dim, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), "user prefers hex over rgb", "preference",
                 None, None, vec_a.tobytes(), "nomic-embed-text", 8,
                 datetime.now().isoformat()),
            )
            conn.commit()

        # Query mock returns a vector similar to vec_a
        async def _fake_embed(texts, model, batch_size=32):
            return [np.array([0.9] + [0.1] * 7, dtype=np.float32)]
        monkeypatch.setattr("backend.long_term_memory._embed_batch", _fake_embed)

        hits = await ltm.recall("color preferences")
        assert len(hits) == 1
        assert hits[0]["fact"] == "user prefers hex over rgb"
        assert hits[0]["score"] > 0.5


class TestListAndDelete:
    def test_list_empty(self, fresh_schema: str) -> None:
        assert ltm.list_memories() == []

    def test_delete(self, fresh_schema: str) -> None:
        import uuid
        from datetime import datetime
        mid = str(uuid.uuid4())
        with database.get_connection() as conn:
            conn.execute(
                "INSERT INTO long_term_memory (id, fact, category, project_id, source_conversation_id, "
                "embedding, embedding_model, dim, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (mid, "x", "general", None, None, b"", "m", 0, datetime.now().isoformat()),
            )
            conn.commit()
        assert len(ltm.list_memories()) == 1
        ltm.delete_memory(mid)
        assert ltm.list_memories() == []
