"""Schema and data lifecycle for the test DB.

These are plain functions, not fixtures — the conftest layer composes them
into fixtures so the lifecycle is visible at one place.
"""

from __future__ import annotations

import contextlib
import shutil

from app.database import Base, engine, init_db
from tests._infra.env import TEST_DB_PATH, TEST_UPLOAD_DIR


def reset_db_state() -> None:
    """Drop & recreate schema, run init_db (migrations + seed)."""
    Base.metadata.drop_all(bind=engine)
    shutil.rmtree(TEST_UPLOAD_DIR, ignore_errors=True)
    init_db()


def cleanup_runtime() -> None:
    """Dispose engine and delete test DB + WAL/journal files. Session-end hook."""
    engine.dispose()
    shutil.rmtree(TEST_UPLOAD_DIR, ignore_errors=True)
    for suffix in ("", "-journal", "-wal", "-shm"):
        path = TEST_DB_PATH.with_name(f"{TEST_DB_PATH.name}{suffix}")
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
