"""Shared pytest fixtures.

Each test that touches the DB gets an isolated temp SQLite file so tests
never mutate the real workspace. Ollama-backed features are patched with
canned responses so tests don't require a running model.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import sys
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
    with contextlib.suppress(FileNotFoundError):
        os.unlink(path)
    for suffix in ("-wal", "-shm", "-journal"):
        with contextlib.suppress(FileNotFoundError):
            os.unlink(path + suffix)


@pytest.fixture
def fresh_schema(temp_db: str) -> str:
    """Initialize every schema against the isolated DB. Returns the path."""
    from backend import artifacts, citations, cost_ledger, database, feedback, long_term_memory, rag, session_notes

    database.init_db()
    rag.ensure_schema()
    long_term_memory.ensure_schema()
    session_notes.ensure_schema()
    feedback.ensure_schema()
    cost_ledger.ensure_schema()
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


# ─── Sandbox availability gate ─────────────────────────────────────────────────


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "requires_sandbox: needs a functional Docker or sandbox-exec backend "
        "(auto-skipped on hosts where neither works)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    from backend import security

    if security._sandbox_kind() != "unavailable":
        return
    skip = pytest.mark.skip(reason="no functional sandbox backend (Docker + sandbox-exec both unavailable)")
    for item in items:
        if "requires_sandbox" in item.keywords:
            item.add_marker(skip)


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
