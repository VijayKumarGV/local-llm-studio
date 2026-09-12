"""Append-only audit log for security-relevant actions.

Records every: tool execution, file upload, message/project/conversation
delete, model comparison, sandbox invocation, feedback change,
memory-extract call, workspace export.

Rows are never updated or deleted from application code — only append.
A retention job can prune old rows, but that's out of scope for now.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any

from backend import database

log = logging.getLogger("studio.audit")


def ensure_schema() -> None:
    with database.get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id TEXT PRIMARY KEY,
                ts TEXT NOT NULL,
                actor TEXT DEFAULT 'user',
                action TEXT NOT NULL,
                resource_type TEXT DEFAULT '',
                resource_id TEXT DEFAULT '',
                request_id TEXT DEFAULT '',
                details TEXT DEFAULT '{}'
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_log(actor);")
        conn.commit()


def record(
    action: str,
    *,
    resource_type: str = "",
    resource_id: str = "",
    details: dict[str, Any] | None = None,
    actor: str = "user",
) -> str:
    """Append one row. Returns the audit_log id. Never raises — logs and
    swallows so instrumentation never breaks a real request."""
    try:
        from backend.middleware import request_id_var

        rid = request_id_var.get()
    except Exception:
        rid = "-"
    log_id = str(uuid.uuid4())
    try:
        # json.dumps + default=str will call str() on unserializable values;
        # if THAT raises, we still don't want to lose the audit row entirely —
        # fall back to a repr-based placeholder.
        try:
            payload = json.dumps(details or {}, default=str)[:8000]
        except Exception as inner:
            payload = json.dumps({"_serialize_error": type(inner).__name__})
        ensure_schema()
        with database.get_connection() as conn:
            conn.execute(
                "INSERT INTO audit_log (id, ts, actor, action, resource_type, resource_id, request_id, details) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    log_id,
                    # microsecond precision so tight loops preserve insert order
                    datetime.now().isoformat(),
                    actor,
                    action,
                    resource_type,
                    resource_id,
                    rid,
                    payload,
                ),
            )
            conn.commit()
    except Exception as e:
        log.warning("audit_log write failed: %s", e)
    return log_id


def list_recent(
    limit: int = 100,
    action: str | None = None,
    resource_type: str | None = None,
) -> list[dict[str, Any]]:
    ensure_schema()
    query = "SELECT id, ts, actor, action, resource_type, resource_id, request_id, details FROM audit_log"
    where: list[str] = []
    params: list[Any] = []
    if action:
        where.append("action = ?")
        params.append(action)
    if resource_type:
        where.append("resource_type = ?")
        params.append(resource_type)
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY ts DESC LIMIT ?"
    params.append(limit)
    with database.get_connection() as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        rows = cur.fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        row = dict(r)
        try:
            row["details"] = json.loads(row["details"])
        except (TypeError, ValueError):
            row["details"] = {}
        out.append(row)
    return out


def count(action: str | None = None) -> int:
    ensure_schema()
    with database.get_connection() as conn:
        cur = conn.cursor()
        if action:
            cur.execute("SELECT COUNT(*) FROM audit_log WHERE action = ?", (action,))
        else:
            cur.execute("SELECT COUNT(*) FROM audit_log")
        return int(cur.fetchone()[0])
