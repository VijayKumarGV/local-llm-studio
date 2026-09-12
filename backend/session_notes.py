"""
Per-conversation scratchpad. The agent uses save_note/read_notes tools to
maintain running notes across turns without polluting message history.

Notes are scoped to a conversation. They're injected into the system prompt
of each new turn so the model always sees its own working memory.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional

from backend import database

MAX_NOTES_INJECTED = 20
MAX_NOTE_CHARS = 800


def ensure_schema() -> None:
    with database.get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS session_notes (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                note_key TEXT DEFAULT '',
                text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations (id) ON DELETE CASCADE
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_session_notes_conv ON session_notes(conversation_id);")
        conn.commit()


def save_note(conversation_id: str, text: str, note_key: str = "") -> Dict[str, Any]:
    if not conversation_id or not text:
        return {"status": "error", "error": "conversation_id and text required"}
    ensure_schema()
    text = str(text)[:MAX_NOTE_CHARS]
    nid = str(uuid.uuid4())
    now = datetime.now().isoformat()
    with database.get_connection() as conn:
        conn.execute(
            "INSERT INTO session_notes (id, conversation_id, note_key, text, created_at) VALUES (?, ?, ?, ?, ?)",
            (nid, conversation_id, note_key or "", text, now),
        )
        conn.commit()
    return {"status": "success", "id": nid, "note_key": note_key, "text": text}


def read_notes(conversation_id: str, note_key: Optional[str] = None) -> List[Dict[str, Any]]:
    if not conversation_id:
        return []
    ensure_schema()
    with database.get_connection() as conn:
        cur = conn.cursor()
        if note_key:
            cur.execute(
                "SELECT id, note_key, text, created_at FROM session_notes "
                "WHERE conversation_id = ? AND note_key = ? ORDER BY created_at",
                (conversation_id, note_key),
            )
        else:
            cur.execute(
                "SELECT id, note_key, text, created_at FROM session_notes "
                "WHERE conversation_id = ? ORDER BY created_at",
                (conversation_id,),
            )
        return [dict(r) for r in cur.fetchall()]


def clear_notes(conversation_id: str, note_key: Optional[str] = None) -> int:
    if not conversation_id:
        return 0
    ensure_schema()
    with database.get_connection() as conn:
        cur = conn.cursor()
        if note_key:
            cur.execute(
                "DELETE FROM session_notes WHERE conversation_id = ? AND note_key = ?",
                (conversation_id, note_key),
            )
        else:
            cur.execute("DELETE FROM session_notes WHERE conversation_id = ?", (conversation_id,))
        n = cur.rowcount
        conn.commit()
    return n


def format_for_prompt(conversation_id: str) -> str:
    """Render notes into a short markdown block for injection into the system
    prompt. Empty if there are no notes."""
    notes = read_notes(conversation_id)[-MAX_NOTES_INJECTED:]
    if not notes:
        return ""
    lines = ["## Your session scratchpad (persists across turns in this conversation)"]
    for n in notes:
        prefix = f"[{n['note_key']}] " if n["note_key"] else "- "
        lines.append(f"{prefix}{n['text']}")
    return "\n".join(lines)
