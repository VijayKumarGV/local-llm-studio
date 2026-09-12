"""Shared pytest fixtures.

Each test that touches the DB gets an isolated temp SQLite file so tests
never mutate the real workspace. Ollama-backed features are patched with
canned responses so tests don't require a running model.
"""

from __future__ import annotations

import os
import sys
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

# Ensure the project root is importable as `backend.*` regardless of where
# pytest is invoked from.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ─── DB isolation ──────────────────────────────────────────────────────────────

@pytest.fixture
def temp_db(monkeypatch: pytest.MonkeyPatch) -> str:
    """Point every backend module at a throwaway SQLite file for this test."""
    fd, path = tempfile.mkstemp(suffix="_studio.db")
    os.close(fd)
    monkeypatch.setattr("backend.database.DB_PATH", path)
    yield path
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    for suffix in ("-wal", "-shm", "-journal"):
        try:
            os.unlink(path + suffix)
        except FileNotFoundError:
            pass


@pytest.fixture
def fresh_schema(temp_db: str) -> str:
    """Initialize every schema against the isolated DB. Returns the path."""
    from backend import database, rag, long_term_memory, session_notes, feedback, artifacts, citations

    database.init_db()
    rag.ensure_schema()
    long_term_memory.ensure_schema()
    session_notes.ensure_schema()
    feedback.ensure_schema()
    # These modules run their init_*_table() at import time (before our monkeypatch
    # of DB_PATH takes effect), so we re-run them explicitly here.
    artifacts.init_artifacts_table()
    citations.init_citations_table()
    return temp_db


# ─── Ollama mocking ────────────────────────────────────────────────────────────

@pytest.fixture
def fake_ollama(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Patch the shared Ollama httpx.AsyncClient with a mock. Tests set
    `.post.return_value.json.return_value = {...}` to script responses."""
    client = AsyncMock()
    monkeypatch.setattr("backend.ollama_client.get_ollama_client", lambda: client)
    return client


# ─── Small utilities ───────────────────────────────────────────────────────────

@pytest.fixture
def fixtures_dir() -> Path:
    return ROOT / "tests" / "fixtures"


def _sqlite_table_names(db_path: str) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r[0] for r in rows}


@pytest.fixture
def sqlite_tables():
    return _sqlite_table_names
