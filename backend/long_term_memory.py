"""
Long-term memory for Local LLM Studio.

Extracts durable facts from a completed conversation (user's stack,
preferences, ongoing projects, non-obvious things worth remembering)
using a small fast model, embeds them, and stores them per project or
globally. On new conversation turns, top-k relevant memories are
retrieved and prepended to the system context so the app "remembers"
across sessions.

Design:
  - Extraction runs opportunistically on demand (POST /api/memory/extract)
    so it never blocks the chat stream. The frontend or a cron can call it.
  - Retrieval reuses the same `nomic-embed-text` embeddings as RAG.
  - Scope: memories are tagged with project_id (for project-scoped) OR
    global (for cross-project user facts).
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional

import numpy as np

from backend import database
from backend.ollama_client import get_ollama_client
from backend.rag import _embed_batch, _current_model, _cosine

DEFAULT_EXTRACTION_MODEL = "qwen2.5:32b"  # reliable JSON output; 1B/3B models hallucinate too much here


def _extraction_model() -> str:
    return database.get_settings().get("memory_extraction_model") or DEFAULT_EXTRACTION_MODEL
MAX_MEMORIES_PER_EXTRACTION = 12

_EXTRACTION_SYSTEM = (
    "Extract durable facts worth remembering from the conversation below. "
    "A fact is worth remembering if it will still be useful in a future "
    "conversation and can't be re-derived from the code. Examples: "
    "the user's role, tech stack, tool preferences, ongoing project "
    "constraints, past incidents, terminology they use. NOT worth remembering: "
    "the current conversation topic, temporary state, one-off questions.\n\n"
    "Return a JSON object of exactly this shape:\n"
    '{"facts": [ {"fact": "…", "category": "…"}, ... ] }\n'
    "Each fact is one clear sentence. Category is one of: "
    "user_profile | preference | project_state | past_incident | general. "
    "Return {\"facts\": []} if nothing durable came up. "
    "Return ONLY the JSON object — no preamble, no code fences, no commentary."
)


def ensure_schema() -> None:
    with database.get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS long_term_memory (
                id TEXT PRIMARY KEY,
                fact TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                project_id TEXT,
                source_conversation_id TEXT,
                embedding BLOB,
                embedding_model TEXT,
                dim INTEGER,
                confidence REAL DEFAULT 1.0,
                created_at TEXT NOT NULL,
                last_used_at TEXT,
                use_count INTEGER DEFAULT 0
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ltm_project ON long_term_memory(project_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ltm_conv ON long_term_memory(source_conversation_id);")
        conn.commit()


def _parse_facts(raw: str) -> List[Dict[str, str]]:
    """LLMs give back arrays, single objects, or objects wrapping a `facts`
    array. Accept all three."""
    if not raw:
        return []
    data = None
    # Try full parse first (works when model returned pure JSON).
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Extract the first array-or-object substring.
        m = re.search(r"[\[\{][\s\S]*[\]\}]", raw)
        if m:
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                return []
    if data is None:
        return []

    # Unwrap common shapes: {"facts":[...]}, {"memories":[...]}, or single {fact:...}
    items: List[Any] = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("facts", "memories", "items", "results"):
            if isinstance(data.get(key), list):
                items = data[key]
                break
        else:
            # Single fact object
            if data.get("fact"):
                items = [data]

    out = []
    for item in items:
        if isinstance(item, dict) and item.get("fact"):
            out.append({
                "fact": str(item["fact"])[:400],
                "category": str(item.get("category") or "general"),
            })
        elif isinstance(item, str):
            out.append({"fact": item[:400], "category": "general"})
    return out[:MAX_MEMORIES_PER_EXTRACTION]


async def extract_from_conversation(
    conversation_id: str,
    replace_existing: bool = False,
) -> Dict[str, Any]:
    """Run the extraction model over a conversation and store the facts."""
    ensure_schema()
    conv = database.get_conversation(conversation_id)
    if not conv:
        return {"status": "error", "error": "conversation not found"}
    messages = conv.get("messages") or []
    if len(messages) < 2:
        return {"status": "empty", "extracted": 0}

    transcript = "\n".join(
        f"{m['role'].upper()}: {m['content'][:800]}" for m in messages if m.get("content")
    )
    if len(transcript) > 16000:
        transcript = transcript[-16000:]

    client = get_ollama_client()
    resp = await client.post(
        "/api/chat",
        json={
            "model": _extraction_model(),
            "stream": False,
            "messages": [
                {"role": "system", "content": _EXTRACTION_SYSTEM},
                {"role": "user", "content": transcript},
            ],
            "options": {"temperature": 0.1},
            "format": "json",
        },
        timeout=90.0,
    )
    resp.raise_for_status()
    raw = (resp.json().get("message") or {}).get("content", "")
    facts = _parse_facts(raw)
    if not facts:
        return {"status": "success", "extracted": 0, "raw": raw[:200]}

    texts = [f["fact"] for f in facts]
    try:
        vectors = await _embed_batch(texts, _current_model())
    except Exception as e:
        return {"status": "error", "error": f"embedding failed: {e}"}

    now = datetime.now().isoformat()
    project_id = conv.get("project_id")
    stored = []
    with database.get_connection() as conn:
        if replace_existing:
            conn.execute(
                "DELETE FROM long_term_memory WHERE source_conversation_id = ?",
                (conversation_id,),
            )
        for f, vec in zip(facts, vectors):
            mid = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO long_term_memory (id, fact, category, project_id, source_conversation_id, embedding, embedding_model, dim, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    mid,
                    f["fact"],
                    f["category"],
                    project_id,
                    conversation_id,
                    vec.tobytes(),
                    _current_model(),
                    int(vec.size),
                    now,
                ),
            )
            stored.append({"id": mid, **f})
        conn.commit()
    return {"status": "success", "extracted": len(stored), "facts": stored}


async def recall(
    query: str,
    project_id: Optional[str] = None,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """Retrieve top-k relevant memories. Includes global memories (project_id
    IS NULL) plus project-scoped ones."""
    ensure_schema()
    if not query.strip():
        return []
    with database.get_connection() as conn:
        cur = conn.cursor()
        if project_id:
            cur.execute(
                "SELECT id, fact, category, project_id, dim, embedding FROM long_term_memory "
                "WHERE embedding IS NOT NULL AND (project_id = ? OR project_id IS NULL)",
                (project_id,),
            )
        else:
            cur.execute(
                "SELECT id, fact, category, project_id, dim, embedding FROM long_term_memory "
                "WHERE embedding IS NOT NULL"
            )
        rows = cur.fetchall()
    if not rows:
        return []
    dim = rows[0]["dim"]
    rows = [r for r in rows if r["dim"] == dim]
    if not rows:
        return []

    model = _current_model()
    try:
        qvec = (await _embed_batch([query], model))[0]
    except Exception:
        return []
    if qvec.size != dim:
        return []

    mat = np.stack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
    scores = _cosine(mat, qvec)
    order = np.argsort(-scores)[:top_k]

    # Bump use_count on the memories we're returning
    now = datetime.now().isoformat()
    hit_ids = [rows[i]["id"] for i in order]
    if hit_ids:
        with database.get_connection() as conn:
            for mid in hit_ids:
                conn.execute(
                    "UPDATE long_term_memory SET last_used_at = ?, use_count = use_count + 1 WHERE id = ?",
                    (now, mid),
                )
            conn.commit()

    return [
        {
            "id": rows[i]["id"],
            "fact": rows[i]["fact"],
            "category": rows[i]["category"],
            "score": float(scores[i]),
        }
        for i in order
    ]


def list_memories(project_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    ensure_schema()
    with database.get_connection() as conn:
        cur = conn.cursor()
        if project_id:
            cur.execute(
                "SELECT id, fact, category, project_id, source_conversation_id, created_at, use_count "
                "FROM long_term_memory WHERE project_id = ? OR project_id IS NULL "
                "ORDER BY created_at DESC LIMIT ?",
                (project_id, limit),
            )
        else:
            cur.execute(
                "SELECT id, fact, category, project_id, source_conversation_id, created_at, use_count "
                "FROM long_term_memory ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        return [dict(r) for r in cur.fetchall()]


def delete_memory(memory_id: str) -> bool:
    with database.get_connection() as conn:
        conn.execute("DELETE FROM long_term_memory WHERE id = ?", (memory_id,))
        conn.commit()
    return True
