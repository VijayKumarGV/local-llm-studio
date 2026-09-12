"""Per-message feedback (👍/👎) — DB roundtrips.

Feedback rows FK to messages, so every test seeds a conversation + message
first via the fresh_schema fixture.
"""

from __future__ import annotations

import pytest

from backend import database, feedback


@pytest.fixture
def seeded_message(fresh_schema: str) -> str:
    """Create a project → conversation → assistant message. Return the msg id."""
    proj = database.create_project(name="P")
    conv = database.create_conversation(title="C", project_id=proj["id"])
    msg = database.add_message(
        conversation_id=conv["id"], role="assistant", content="hi from ai",
    )
    return msg["id"]


class TestRecord:
    def test_record_thumbs_up(self, seeded_message: str) -> None:
        r = feedback.record(seeded_message, 1)
        assert r["status"] == "success"
        got = feedback.get_for_message(seeded_message)
        assert got is not None
        assert got["rating"] == 1

    def test_record_thumbs_down(self, seeded_message: str) -> None:
        feedback.record(seeded_message, -1)
        got = feedback.get_for_message(seeded_message)
        assert got is not None
        assert got["rating"] == -1

    def test_rating_replaces_previous(self, seeded_message: str) -> None:
        feedback.record(seeded_message, 1)
        feedback.record(seeded_message, -1)
        got = feedback.get_for_message(seeded_message)
        assert got is not None
        assert got["rating"] == -1  # latest wins

    def test_rating_zero_deletes_row(self, seeded_message: str) -> None:
        feedback.record(seeded_message, 1)
        feedback.record(seeded_message, 0)
        assert feedback.get_for_message(seeded_message) is None

    def test_invalid_rating_rejected(self, seeded_message: str) -> None:
        r = feedback.record(seeded_message, 5)
        assert r["status"] == "error"

    def test_missing_message_id_rejected(self, fresh_schema: str) -> None:
        r = feedback.record("nonexistent-message-id", 1)
        assert r["status"] == "error"

    def test_note_persisted(self, seeded_message: str) -> None:
        feedback.record(seeded_message, -1, note="wrong CVE reference")
        got = feedback.get_for_message(seeded_message)
        assert got is not None
        assert got["note"] == "wrong CVE reference"

    def test_message_delete_cascades_feedback(self, seeded_message: str) -> None:
        feedback.record(seeded_message, 1)
        database.delete_message(seeded_message)
        # FK ON DELETE CASCADE should have wiped the feedback row
        assert feedback.get_for_message(seeded_message) is None


class TestSummary:
    def test_empty_summary(self, fresh_schema: str) -> None:
        s = feedback.summary()
        assert s == {"up": 0, "down": 0}

    def test_counts_across_messages(self, fresh_schema: str) -> None:
        proj = database.create_project(name="P")
        conv = database.create_conversation(title="C", project_id=proj["id"])
        for _ in range(3):
            m = database.add_message(conv["id"], "assistant", "x")
            feedback.record(m["id"], 1)
        for _ in range(2):
            m = database.add_message(conv["id"], "assistant", "x")
            feedback.record(m["id"], -1)
        s = feedback.summary()
        assert s == {"up": 3, "down": 2}

    def test_scoped_by_conversation(self, fresh_schema: str) -> None:
        proj = database.create_project(name="P")
        conv_a = database.create_conversation(title="A", project_id=proj["id"])
        conv_b = database.create_conversation(title="B", project_id=proj["id"])
        m_a = database.add_message(conv_a["id"], "assistant", "x")
        m_b = database.add_message(conv_b["id"], "assistant", "x")
        feedback.record(m_a["id"], 1)
        feedback.record(m_b["id"], -1)
        s = feedback.summary(conv_a["id"])
        assert s == {"up": 1, "down": 0}
        s = feedback.summary(conv_b["id"])
        assert s == {"up": 0, "down": 1}
