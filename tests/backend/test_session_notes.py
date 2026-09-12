"""Per-conversation scratchpad — DB roundtrips."""

from __future__ import annotations

import sqlite3

import pytest

from backend import database, session_notes


@pytest.fixture
def conversation_id(fresh_schema: str) -> str:
    proj = database.create_project(name="P")
    conv = database.create_conversation(title="C", project_id=proj["id"])
    return conv["id"]


class TestSaveNote:
    def test_save_and_read_back(self, conversation_id: str) -> None:
        r = session_notes.save_note(conversation_id, "plan: outline first", "plan")
        assert r["status"] == "success"
        assert r["note_key"] == "plan"
        notes = session_notes.read_notes(conversation_id)
        assert len(notes) == 1
        assert notes[0]["text"] == "plan: outline first"
        assert notes[0]["note_key"] == "plan"

    def test_empty_conversation_id_rejected(self, fresh_schema: str) -> None:
        r = session_notes.save_note("", "some text")
        assert r["status"] == "error"

    def test_empty_text_rejected(self, conversation_id: str) -> None:
        r = session_notes.save_note(conversation_id, "")
        assert r["status"] == "error"

    def test_missing_conversation_fires_fk_constraint(self, fresh_schema: str) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            session_notes.save_note("does-not-exist", "orphan note")

    def test_note_key_optional(self, conversation_id: str) -> None:
        session_notes.save_note(conversation_id, "unlabeled")
        notes = session_notes.read_notes(conversation_id)
        assert notes[0]["note_key"] == ""

    def test_long_note_truncated_to_cap(self, conversation_id: str) -> None:
        session_notes.save_note(conversation_id, "x" * 5000)
        notes = session_notes.read_notes(conversation_id)
        assert len(notes[0]["text"]) == session_notes.MAX_NOTE_CHARS


class TestReadNotes:
    def test_empty_when_no_notes(self, conversation_id: str) -> None:
        assert session_notes.read_notes(conversation_id) == []

    def test_returns_all_in_order(self, conversation_id: str) -> None:
        for i in range(3):
            session_notes.save_note(conversation_id, f"note {i}")
        notes = session_notes.read_notes(conversation_id)
        assert [n["text"] for n in notes] == ["note 0", "note 1", "note 2"]

    def test_filter_by_note_key(self, conversation_id: str) -> None:
        session_notes.save_note(conversation_id, "plan A", "plan")
        session_notes.save_note(conversation_id, "todo X", "todo")
        session_notes.save_note(conversation_id, "plan B", "plan")
        only_plans = session_notes.read_notes(conversation_id, "plan")
        assert len(only_plans) == 2
        assert all(n["note_key"] == "plan" for n in only_plans)

    def test_isolated_per_conversation(self, fresh_schema: str) -> None:
        proj = database.create_project(name="P")
        a = database.create_conversation(title="A", project_id=proj["id"])["id"]
        b = database.create_conversation(title="B", project_id=proj["id"])["id"]
        session_notes.save_note(a, "for A")
        session_notes.save_note(b, "for B")
        assert session_notes.read_notes(a)[0]["text"] == "for A"
        assert session_notes.read_notes(b)[0]["text"] == "for B"

    def test_read_with_empty_conversation_id_returns_empty(self, fresh_schema: str) -> None:
        assert session_notes.read_notes("") == []


class TestClearNotes:
    def test_clear_all(self, conversation_id: str) -> None:
        for _ in range(3):
            session_notes.save_note(conversation_id, "x")
        n = session_notes.clear_notes(conversation_id)
        assert n == 3
        assert session_notes.read_notes(conversation_id) == []

    def test_clear_by_key(self, conversation_id: str) -> None:
        session_notes.save_note(conversation_id, "keep me", "keep")
        session_notes.save_note(conversation_id, "drop me", "drop")
        session_notes.clear_notes(conversation_id, "drop")
        remaining = session_notes.read_notes(conversation_id)
        assert len(remaining) == 1
        assert remaining[0]["text"] == "keep me"


class TestFormatForPrompt:
    def test_empty_when_no_notes(self, conversation_id: str) -> None:
        assert session_notes.format_for_prompt(conversation_id) == ""

    def test_renders_with_labels(self, conversation_id: str) -> None:
        session_notes.save_note(conversation_id, "step 1", "plan")
        session_notes.save_note(conversation_id, "beware race condition", "constraint")
        out = session_notes.format_for_prompt(conversation_id)
        assert "scratchpad" in out.lower()
        assert "[plan]" in out
        assert "step 1" in out
        assert "beware race condition" in out

    def test_caps_at_max_injected(self, conversation_id: str) -> None:
        for i in range(50):
            session_notes.save_note(conversation_id, f"note {i}")
        out = session_notes.format_for_prompt(conversation_id)
        # Only the latest MAX_NOTES_INJECTED are included
        assert "note 49" in out
        assert "note 0" not in out
