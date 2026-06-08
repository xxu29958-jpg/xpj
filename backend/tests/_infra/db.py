"""Schema and data lifecycle for the test DB.

These are plain functions, not fixtures — the conftest layer composes them
into fixtures so the lifecycle is visible at one place.

Two reset strategies (see :func:`is_isolation_lane`):

* **SQLite lanes** — per-test ``reset_db_state`` (drop + create + seed). In-memory
  ``create_all`` is ~16ms, cheap enough, and the per-test rebuild keeps the
  SQLite-only machinery tests honest.
* **PostgreSQL lane** — schema + base seed built ONCE per session, then each test
  runs inside an outer transaction that is rolled back (``transactional_isolation``).
  Per-test rebuild on PostgreSQL is ~590ms (``create_all`` + 18-rev Alembic
  replay); the rollback model drops that to ~1ms, approaching the SQLite floor.
"""

from __future__ import annotations

import contextlib
import shutil
from collections.abc import Iterator

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


def is_isolation_lane() -> bool:
    """True on the PostgreSQL lane, where per-test transaction-rollback applies.

    SQLite lanes return False and keep per-test ``reset_db_state``: in-memory
    ``create_all`` is cheap, and the rollback model conflicts with idempotency's
    SQLite-only ``BEGIN IMMEDIATE`` writer shim (a raw ``BEGIN`` issued inside the
    test's already-open outer transaction). PostgreSQL has no such shim — there
    the shim is a dialect no-op — so the SAVEPOINT-nesting model is clean.
    """
    from app.database import settings

    return not settings.database_url.startswith("sqlite")


@contextlib.contextmanager
def transactional_isolation() -> Iterator[None]:
    """Run a test inside one connection's transaction, rolled back at teardown.

    Rebinds the shared ``SessionLocal`` to a single checked-out connection with
    ``join_transaction_mode="create_savepoint"`` so every session opened ON THE
    CALLING THREAD during the test — route ``get_db`` sessions AND the app's
    direct ``SessionLocal()`` call sites (``web_session`` middleware, seeders) —
    joins that connection's transaction via a SAVEPOINT. An in-app ``db.commit()``
    then releases its SAVEPOINT (the rows stay in the outer transaction, visible
    to the rest of the test on the same connection) instead of committing. The
    final ``transaction.rollback()`` discards everything, isolating one test from
    the next without rebuilding the schema.

    Work that opens a session on ANOTHER thread — a FastAPI ``BackgroundTask``
    such as ``enrich_pending_expense`` — cannot safely share this single
    connection, so tests asserting on that output opt out via
    ``@pytest.mark.real_db`` (see conftest ``_PG_REAL_DB_NODES``).

    SessionLocal is restored to its engine binding BEFORE the rollback so a
    rollback hiccup can't leave a later test bound to a closed connection.
    """
    from app.database import SessionLocal

    # The DB rollback below undoes row writes, but saved upload files live on
    # disk outside any transaction. Clear the upload dir so one test's saved
    # images don't leak into the next (the per-test reset_db_state did this on
    # the SQLite lane; the isolation lane must do it explicitly).
    shutil.rmtree(TEST_UPLOAD_DIR, ignore_errors=True)
    connection = engine.connect()
    # Acquisition is inside the try so a raise from begin()/configure() can't
    # leak the checked-out connection (pool is small; a leak would cascade into
    # connection-exhaustion for the rest of the run).
    try:
        transaction = connection.begin()
        SessionLocal.configure(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield
        finally:
            SessionLocal.configure(bind=engine, join_transaction_mode="conditional_savepoint")
            transaction.rollback()
    finally:
        connection.close()
