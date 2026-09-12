"""
Cost ledger — token accounting per chat completion.

We're running local models, so "cost" is a proxy for compute usage
(there's no billing to reconcile). Recording per-turn prompt + completion
tokens by workspace and model lets the operator answer:

  - which workspace burned the most compute this week?
  - is llama3.2:3b really 5x cheaper than qwen2.5:32b for our queries?
  - are the eval sets themselves dominating our token spend?

Schema is intentionally small — one row per completion, no aggregates on
disk. Aggregation happens in the `summary()` query so we can slice by
day / workspace / model without pre-committing to a rollup shape.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

from backend import database

log = logging.getLogger("studio.cost_ledger")


def ensure_schema() -> None:
    with database.get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cost_ledger (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                conversation_id TEXT,
                project_id TEXT,
                model TEXT NOT NULL,
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER GENERATED ALWAYS AS
                    (prompt_tokens + completion_tokens) STORED
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cost_ledger_ts ON cost_ledger(created_at);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cost_ledger_proj ON cost_ledger(project_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cost_ledger_model ON cost_ledger(model);")
        conn.commit()


def record(
    conversation_id: str | None,
    project_id: str | None,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> None:
    """Append a completion row. Best-effort — swallows DB errors so a
    logging failure never breaks the chat response the user is waiting on."""
    if prompt_tokens < 0 or completion_tokens < 0:
        return
    if prompt_tokens == 0 and completion_tokens == 0:
        return
    try:
        ensure_schema()
        with database.get_connection() as conn:
            conn.execute(
                "INSERT INTO cost_ledger "
                "(id, created_at, conversation_id, project_id, model, prompt_tokens, completion_tokens) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    datetime.now(UTC).isoformat(),
                    conversation_id,
                    project_id,
                    model,
                    int(prompt_tokens),
                    int(completion_tokens),
                ),
            )
            conn.commit()
    except sqlite3.Error as e:
        log.warning("cost_ledger.record failed: %s", e)


def summary(
    since_iso: str | None = None,
    group_by: str = "model",
) -> list[dict[str, Any]]:
    """Aggregate the ledger. `group_by` must be one of: model, project, day.
    `since_iso` filters by created_at (>=)."""
    if group_by not in {"model", "project", "day"}:
        raise ValueError("group_by must be model|project|day")
    ensure_schema()

    if group_by == "model":
        col = "model"
        select_expr = "model AS bucket"
    elif group_by == "project":
        col = "project_id"
        select_expr = "COALESCE(project_id, '(none)') AS bucket"
    else:
        col = "date(created_at)"
        select_expr = "date(created_at) AS bucket"

    where = ""
    params: list[Any] = []
    if since_iso:
        where = " WHERE created_at >= ?"
        params.append(since_iso)

    sql = (
        f"SELECT {select_expr}, "
        f"       COUNT(*) AS completions, "
        f"       SUM(prompt_tokens) AS prompt_tokens, "
        f"       SUM(completion_tokens) AS completion_tokens, "
        f"       SUM(total_tokens) AS total_tokens "
        f"FROM cost_ledger{where} "
        f"GROUP BY {col} "
        f"ORDER BY total_tokens DESC"
    )

    with database.get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]
