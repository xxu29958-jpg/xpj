"""Schema and data lifecycle for the test DB.

These are plain functions, not fixtures — the conftest layer composes them
into fixtures so the lifecycle is visible at one place.

PG-only (debt #4): schema + base seed are built ONCE per session, then each test
runs inside an outer transaction that is rolled back (``transactional_isolation``).
Per-test rebuild on PostgreSQL is ~590ms (``create_all`` + 18-rev Alembic replay);
the rollback model drops that to ~1ms. ``reset_db_state`` (full rebuild) still owns
the session build and the ``@pytest.mark.real_db`` tests that need real
cross-connection commits.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator

from sqlalchemy import text

from app.database import engine, init_db
from scripts.test_pg_contract import validate_test_database_name
from tests._infra.env import (
    BACKEND_ROOT,
    TEST_DATA_DIR,
    TEST_RUNTIME_ROOT,
    TEST_UPLOAD_DIR,
)
from tests._infra.runtime_fs import remove_owned_runtime_tree


def _cleanup_runtime_paths(*, include_data: bool) -> None:
    targets = [
        (
            TEST_UPLOAD_DIR,
            BACKEND_ROOT / "uploads",
            "Test upload runtime directory",
        )
    ]
    if include_data:
        targets.insert(
            0,
            (
                TEST_DATA_DIR,
                TEST_RUNTIME_ROOT,
                "Test application runtime directory",
            ),
        )
    with contextlib.ExitStack() as cleanup:
        for path, root, label in targets:
            cleanup.callback(
                remove_owned_runtime_tree,
                path,
                owned_root=root,
                label=label,
            )


def reset_db_state() -> None:
    """Recreate the test schema, then run migrations and seed data.

    ``Base.metadata.drop_all`` cannot remove objects introduced by a newer or
    different branch because the current ORM does not know their dependency
    graph. Rebuilding ``public`` makes repeated branch runs hermetic. The name
    guard keeps this destructive test helper away from non-test databases.
    """

    database_name = engine.url.database or ""
    try:
        validate_test_database_name(database_name)
    except ValueError as exc:
        raise RuntimeError(
            f"Refusing to reset non-test PostgreSQL database: {database_name!r}"
        ) from exc
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    _cleanup_runtime_paths(include_data=True)
    init_db()


def cleanup_runtime() -> None:
    """Dispose the engine and clear this process's writable test data."""
    try:
        engine.dispose()
    finally:
        _cleanup_runtime_paths(include_data=True)


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
    an explicit ``@pytest.mark.real_db`` declaration.

    SessionLocal is restored to its engine binding BEFORE the rollback so a
    rollback hiccup can't leave a later test bound to a closed connection.
    """
    from app.database import SessionLocal

    # The DB rollback below undoes row writes, but saved upload files live on
    # disk outside any transaction. Clear the upload dir so one test's saved
    # images don't leak into the next (the rolled-back transaction can't reclaim
    # files written during the test).
    _cleanup_runtime_paths(include_data=False)
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
