"""
First-Class Citations Engine for Local LLM Studio.
Stores and links web sources, uploaded documents, and tool observations to AI messages.
"""

import uuid
from datetime import datetime
from typing import Any

from backend import database


def init_citations_table():
    with database.get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS citations (
                id TEXT PRIMARY KEY,
                message_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                source_type TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT DEFAULT '',
                snippet TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (message_id) REFERENCES messages (id) ON DELETE CASCADE,
                FOREIGN KEY (conversation_id) REFERENCES conversations (id) ON DELETE CASCADE
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_citations_msg ON citations(message_id);")
        conn.commit()


init_citations_table()


def add_citation(
    message_id: str, conversation_id: str, source_type: str, title: str, snippet: str, url: str = ""
) -> dict[str, Any]:
    now = datetime.now().isoformat()
    cid = str(uuid.uuid4())

    with database.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO citations (id, message_id, conversation_id, source_type, title, url, snippet, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (cid, message_id, conversation_id, source_type, title, url, snippet, now),
        )
        conn.commit()

    return {
        "id": cid,
        "message_id": message_id,
        "conversation_id": conversation_id,
        "source_type": source_type,
        "title": title,
        "url": url,
        "snippet": snippet,
        "created_at": now,
    }


def list_citations_for_message(message_id: str) -> list[dict[str, Any]]:
    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM citations WHERE message_id = ?", (message_id,))
        return [dict(r) for r in cursor.fetchall()]
