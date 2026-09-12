"""Thin wrapper around yoyo-migrations for the SQLite workspace DB."""

import os
import logging
from typing import Optional

log = logging.getLogger("studio.migrations")

MIGRATIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations"
)


def apply_migrations(db_path: str) -> Optional[int]:
    """Apply all outstanding migrations. Returns the number applied, or None
    if yoyo isn't installed."""
    try:
        from yoyo import read_migrations, get_backend
    except Exception as e:
        log.warning("yoyo not available, skipping migrations: %s", e)
        return None

    backend = get_backend(f"sqlite:///{db_path}")
    migrations = read_migrations(MIGRATIONS_DIR)
    to_apply = backend.to_apply(migrations)
    with backend.lock():
        backend.apply_migrations(to_apply)
    return len(to_apply)
