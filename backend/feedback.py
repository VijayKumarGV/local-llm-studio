"""
Per-message feedback (👍/👎 + optional note). Foundation for later
retrieval-weight tuning or LoRA fine-tune candidate selection.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional

from backend import database


def ensure_schema() -> None:
    with database.get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS message_feedback (
                id TEXT PRIMARY KEY,
                message_id TEXT NOT NULL,
                conversation_id TEXT,
                rating INTEGER NOT NULL,          -- +1 / -1
                note TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (message_id) REFERENCES messages (id) ON DELETE CASCADE
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_msg ON message_feedback(message_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_conv ON message_feedback(conversation_id);")
        conn.commit()


def record(message_id: str, rating: int, note: str = "") -> Dict[str, Any]:
    """Record a rating. Later ratings on the same message replace earlier ones."""
    if rating not in (-1, 0, 1):
        return {"status": "error", "error": "rating must be -1, 0, or 1"}
    ensure_schema()
    now = datetime.now().isoformat()
    with database.get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT conversation_id FROM messages WHERE id = ?", (message_id,))
        row = cur.fetchone()
        if not row:
            return {"status": "error", "error": "message not found"}
        conv_id = row["conversation_id"]
        cur.execute("DELETE FROM message_feedback WHERE message_id = ?", (message_id,))
        if rating != 0:  # rating=0 means "unrate"
            cur.execute(
                "INSERT INTO message_feedback (id, message_id, conversation_id, rating, note, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), message_id, conv_id, rating, note or "", now),
            )
        conn.commit()
    return {"status": "success", "message_id": message_id, "rating": rating}


def get_for_message(message_id: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    with database.get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, rating, note, created_at FROM message_feedback WHERE message_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (message_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def summary(conversation_id: Optional[str] = None) -> Dict[str, Any]:
    ensure_schema()
    with database.get_connection() as conn:
        cur = conn.cursor()
        if conversation_id:
            cur.execute(
                "SELECT rating, COUNT(*) as n FROM message_feedback WHERE conversation_id = ? GROUP BY rating",
                (conversation_id,),
            )
        else:
            cur.execute("SELECT rating, COUNT(*) as n FROM message_feedback GROUP BY rating")
        counts = {"up": 0, "down": 0}
        for r in cur.fetchall():
            if r["rating"] == 1:
                counts["up"] = r["n"]
            elif r["rating"] == -1:
                counts["down"] = r["n"]
        return counts
