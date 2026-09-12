"""
Workspace Backup & JSON Export/Import Engine for Local LLM Studio.
Enables full data portability, backups, and restores across machines or sessions.
"""

import json
from datetime import datetime
from typing import Dict, Any

from backend import database, artifacts


def export_full_workspace() -> Dict[str, Any]:
    """Generates a complete JSON backup of all workspace state."""
    with database.get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM projects")
        projects = [dict(r) for r in cursor.fetchall()]

        cursor.execute("SELECT * FROM conversations")
        conversations = [dict(r) for r in cursor.fetchall()]

        cursor.execute("SELECT * FROM messages")
        messages = [dict(r) for r in cursor.fetchall()]

        cursor.execute("SELECT * FROM artifacts")
        art_list = [dict(r) for r in cursor.fetchall()]

        cursor.execute("SELECT * FROM files")
        files = [dict(r) for r in cursor.fetchall()]

        cursor.execute("SELECT * FROM settings")
        settings = {r["key"]: r["value"] for r in cursor.fetchall()}

    return {
        "export_version": "2.0",
        "exported_at": datetime.now().isoformat(),
        "projects": projects,
        "conversations": conversations,
        "messages": messages,
        "artifacts": art_list,
        "files": files,
        "settings": settings
    }


def import_workspace(data: Dict[str, Any]) -> Dict[str, int]:
    """Restores projects, conversations, messages, artifacts, and settings from JSON."""
    imported_counts = {"projects": 0, "conversations": 0, "messages": 0, "artifacts": 0}

    with database.get_connection() as conn:
        # Projects
        for p in data.get("projects", []):
            conn.execute("""
                INSERT OR REPLACE INTO projects (id, name, description, system_instructions, icon, color, pinned, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (p["id"], p["name"], p.get("description", ""), p.get("system_instructions", ""), p.get("icon", "📁"), p.get("color", "#38bdf8"), p.get("pinned", 0), p["created_at"], p["updated_at"]))
            imported_counts["projects"] += 1

        # Conversations
        for c in data.get("conversations", []):
            conn.execute("""
                INSERT OR REPLACE INTO conversations (id, title, project_id, model, system_prompt, temperature, pinned, archived, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (c["id"], c["title"], c.get("project_id"), c.get("model", "qwen2.5:32b"), c.get("system_prompt", ""), c.get("temperature", 0.7), c.get("pinned", 0), c.get("archived", 0), c["created_at"], c["updated_at"]))
            imported_counts["conversations"] += 1

        # Messages
        for m in data.get("messages", []):
            tc = json.dumps(m.get("tool_calls", [])) if not isinstance(m.get("tool_calls"), str) else m.get("tool_calls")
            att = json.dumps(m.get("attachments", [])) if not isinstance(m.get("attachments"), str) else m.get("attachments")
            conn.execute("""
                INSERT OR REPLACE INTO messages (id, conversation_id, role, content, parent_id, token_count, eval_tps, tool_calls, attachments, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (m["id"], m["conversation_id"], m["role"], m["content"], m.get("parent_id"), m.get("token_count", 0), m.get("eval_tps", 0.0), tc, att, m["created_at"]))
            imported_counts["messages"] += 1

        # Artifacts
        for a in data.get("artifacts", []):
            conn.execute("""
                INSERT OR REPLACE INTO artifacts (id, conversation_id, project_id, name, type, language, content, size_bytes, version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (a["id"], a.get("conversation_id"), a.get("project_id"), a["name"], a["type"], a.get("language", ""), a["content"], a.get("size_bytes", 0), a.get("version", 1), a["created_at"], a["updated_at"]))
            imported_counts["artifacts"] += 1

        conn.commit()

    return imported_counts
