"""Tests for scripts/feedback_digest.py.

The script isn't inside `backend/`, but its logic touches the message +
feedback tables and is worth testing at the same level as the rest of
the code. We import it via the file path since scripts/ isn't on
sys.path by default.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "feedback_digest.py"

spec = importlib.util.spec_from_file_location("feedback_digest", SCRIPT)
assert spec is not None and spec.loader is not None
feedback_digest = importlib.util.module_from_spec(spec)
sys.modules["feedback_digest"] = feedback_digest
spec.loader.exec_module(feedback_digest)


# ── helpers ───────────────────────────────────────────────────────────


def _seed_db(path: Path) -> None:
    """Create a minimal schema mirroring the runtime one, then insert
    two downvoted messages + one upvoted control row."""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE conversations (
            id TEXT PRIMARY KEY, project_id TEXT, model TEXT
        );
        CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT,
            role TEXT,
            content TEXT,
            created_at TEXT
        );
        CREATE TABLE message_feedback (
            id TEXT PRIMARY KEY,
            message_id TEXT,
            conversation_id TEXT,
            rating INTEGER,
            note TEXT,
            created_at TEXT
        );
        """
    )
    now = datetime.now(UTC)
    conn.execute("INSERT INTO projects VALUES (?, ?)", ("p-sec", "Security Expert"))
    conn.execute("INSERT INTO projects VALUES (?, ?)", ("p-cod", "Coding Expert"))
    conn.execute("INSERT INTO conversations VALUES (?, ?, ?)", ("c-1", "p-sec", "qwen2.5:32b"))
    conn.execute("INSERT INTO conversations VALUES (?, ?, ?)", ("c-2", "p-cod", "llama3.2:3b"))

    def _msg(cid: str, role: str, text: str, offset_s: int) -> str:
        mid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO messages VALUES (?, ?, ?, ?, ?)",
            (mid, cid, role, text, (now - timedelta(seconds=offset_s)).isoformat()),
        )
        return mid

    # downvoted assistant in Security
    _msg("c-1", "user", "How do I use argon2 for password storage?", 60)
    a1 = _msg("c-1", "assistant", "Use MD5 — it's fine.", 55)
    # downvoted assistant in Coding
    _msg("c-2", "user", "What does the ? operator do in Rust?", 60)
    a2 = _msg("c-2", "assistant", "? only works with Option, actually.", 55)
    # upvoted assistant (should NOT appear in digest)
    _msg("c-1", "user", "Explain CSRF briefly.", 40)
    a3 = _msg("c-1", "assistant", "CSRF is …", 35)

    for mid, cid, rating, note, sec in ((a1, "c-1", -1, "wrong", 50), (a2, "c-2", -1, "", 50), (a3, "c-1", +1, "", 30)):
        conn.execute(
            "INSERT INTO message_feedback VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                mid,
                cid,
                rating,
                note,
                (now - timedelta(seconds=sec)).isoformat(),
            ),
        )
    conn.commit()
    conn.close()


# ── tests ─────────────────────────────────────────────────────────────


class TestWeekKey:
    def test_iso_week_format(self) -> None:
        # Mid-year date to avoid week-53 wraparound noise.
        dt = datetime(2026, 6, 15, tzinfo=UTC)
        assert feedback_digest._week_key(dt) == "2026-W25"


class TestFetchDownvotes:
    def test_only_negative_ratings_returned(self, tmp_path: Path) -> None:
        db = tmp_path / "w.db"
        _seed_db(db)
        rows = feedback_digest._fetch_downvotes(db, (datetime.now(UTC) - timedelta(days=1)).isoformat())
        assert len(rows) == 2  # the +1 row is excluded
        assert {r["project_name"] for r in rows} == {"Security Expert", "Coding Expert"}

    def test_window_excludes_old_rows(self, tmp_path: Path) -> None:
        db = tmp_path / "w.db"
        _seed_db(db)
        # Cut-off after seeded rows → zero
        rows = feedback_digest._fetch_downvotes(db, (datetime.now(UTC) + timedelta(days=1)).isoformat())
        assert rows == []


class TestGrouping:
    def test_group_counts_falls_back_when_missing(self) -> None:
        rows = [{"model": "a"}, {"model": "a"}, {"model": None}]
        counts = feedback_digest._group_counts(rows, "model")
        # None-typed values fall through to the '(none)' bucket
        assert counts["a"] == 2
        assert counts["(none)"] + counts["None"] == 1  # depending on stringification


class TestThemeWords:
    def test_filters_stopwords_and_shorts(self) -> None:
        rows = [
            {"user_prompt": "The password storage argon2"},
            {"user_prompt": "password argon2 salt"},
        ]
        themes = dict(feedback_digest._theme_words(rows))
        assert "the" not in themes
        assert themes.get("password") == 2
        assert themes.get("argon2") == 2

    def test_handles_missing_prompt(self) -> None:
        rows = [{"user_prompt": None}, {"user_prompt": ""}]
        assert feedback_digest._theme_words(rows) == []


class TestRenderMarkdown:
    def test_empty_rows_message(self) -> None:
        md = feedback_digest.render_markdown([], datetime.now(UTC), "2026-W37")
        assert "No negative feedback" in md
        assert "Feedback digest — 2026-W37" in md

    def test_populated_report_includes_sections(self, tmp_path: Path) -> None:
        db = tmp_path / "w.db"
        _seed_db(db)
        rows = feedback_digest._fetch_downvotes(db, (datetime.now(UTC) - timedelta(days=1)).isoformat())
        md = feedback_digest.render_markdown(rows, datetime.now(UTC) - timedelta(days=7), "2026-W37")
        assert "By workspace" in md
        assert "By model" in md
        assert "Security Expert" in md
        assert "Coding Expert" in md
        assert "Top prompt themes" in md
        assert "argon2" in md  # theme extracted from the seeded user prompt


class TestMainWritesFile:
    def test_writes_to_configured_out_path(self, tmp_path: Path) -> None:
        db = tmp_path / "w.db"
        _seed_db(db)
        out = tmp_path / "digest.md"
        rc = feedback_digest.main(["--db", str(db), "--days", "7", "--out", str(out)])
        assert rc == 0
        assert out.exists()
        body = out.read_text()
        assert "Total 👎: **2**" in body
