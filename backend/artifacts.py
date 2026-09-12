"""
First-Class Artifact Management Engine for Local LLM Studio.
Handles generated documents, code files, HTML previews, and data tables.
"""

import os
import re
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional

from backend import database

ARTIFACTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "artifacts")
os.makedirs(ARTIFACTS_DIR, exist_ok=True)


def init_artifacts_table():
    """Ensure artifacts table exists in SQLite database."""
    with database.get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY,
                conversation_id TEXT,
                project_id TEXT,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                language TEXT DEFAULT '',
                content TEXT NOT NULL,
                size_bytes INTEGER DEFAULT 0,
                version INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations (id) ON DELETE CASCADE,
                FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE SET NULL
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_conv ON artifacts(conversation_id);")
        conn.commit()


init_artifacts_table()


def save_artifact(
    name: str,
    artifact_type: str,
    content: str,
    conversation_id: Optional[str] = None,
    project_id: Optional[str] = None,
    language: str = ""
) -> Dict[str, Any]:
    """Persist artifact to disk and SQLite."""
    now = datetime.now().isoformat()
    art_id = str(uuid.uuid4())
    size_bytes = len(content.encode("utf-8"))

    # Save physical copy to disk
    file_path = os.path.join(ARTIFACTS_DIR, f"{art_id}_{name}")
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        print(f"Failed to write physical artifact: {e}")

    with database.get_connection() as conn:
        conn.execute("""
            INSERT INTO artifacts (id, conversation_id, project_id, name, type, language, content, size_bytes, version, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        """, (art_id, conversation_id, project_id, name, artifact_type, language, content, size_bytes, now, now))
        conn.commit()

    return {
        "id": art_id,
        "name": name,
        "type": artifact_type,
        "language": language,
        "content": content,
        "size_bytes": size_bytes,
        "conversation_id": conversation_id,
        "project_id": project_id,
        "created_at": now
    }


def get_artifact(artifact_id: str) -> Optional[Dict[str, Any]]:
    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def list_artifacts(conversation_id: Optional[str] = None, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
    with database.get_connection() as conn:
        cursor = conn.cursor()
        if conversation_id:
            cursor.execute("SELECT * FROM artifacts WHERE conversation_id = ? ORDER BY created_at DESC", (conversation_id,))
        elif project_id:
            cursor.execute("SELECT * FROM artifacts WHERE project_id = ? ORDER BY created_at DESC", (project_id,))
        else:
            cursor.execute("SELECT * FROM artifacts ORDER BY created_at DESC LIMIT 50")
        return [dict(r) for r in cursor.fetchall()]


def extract_and_save_artifacts(text: str, conversation_id: Optional[str] = None, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Scans generated text for <artifact name="..." type="..." language="...">...</artifact> tags,
    saves them to the database, and returns the records.
    """
    pattern = r'<artifact\s+name=["\']([^"\']+)["\'](?:\s+type=["\']([^"\']+)["\'])?(?:\s+language=["\']([^"\']+)["\'])?\s*>([\s\S]*?)</artifact>'
    matches = re.findall(pattern, text, re.IGNORECASE)
    created = []

    for name, art_type, lang, content in matches:
        resolved_type = art_type or "code"
        created.append(save_artifact(
            name=name.strip(),
            artifact_type=resolved_type.strip(),
            content=content.strip(),
            conversation_id=conversation_id,
            project_id=project_id,
            language=lang.strip() if lang else ""
        ))

    return created
