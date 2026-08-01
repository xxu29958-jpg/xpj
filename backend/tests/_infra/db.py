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
import errno
import os
import re
import shutil
import stat
import time
from collections.abc import Iterator
from pathlib import Path

from app.database import engine, init_db
from scripts.test_postgres_contract import TEST_POSTGRES_CONTRACT
from tests._infra.c07_alembic import reset_public_schema
from tests._infra.env import BACKEND_ROOT, TEST_RUN_ID

_UPLOAD_RUNTIME_ROOT = Path(os.path.abspath(BACKEND_ROOT / "uploads"))
_DATA_RUNTIME_ROOT = Path(os.path.abspath(BACKEND_ROOT / "ticketbox-data" / "pytest"))
_RUNTIME_LOCK_PATH = TEST_POSTGRES_CONTRACT.runtime_root() / ".pytest-suite.lock"
_RUNTIME_LOCK_TIMEOUT_SECONDS = 30.0
_TEST_RUN_ID = re.compile(r"(?:pid_\d+|xdist_[0-9a-f]{10}_gw\d+)")
_WINDOWS_REPARSE_POINT = 0x400


def _lexical_absolute(path: Path) -> Path:
    """Normalize a path without following its final directory entry."""
    return Path(os.path.abspath(os.fspath(path)))


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.fspath(left)) == os.path.normcase(os.fspath(right))


def _is_reparse(stat_result: os.stat_result) -> bool:
    return stat.S_ISLNK(stat_result.st_mode) or bool(
        getattr(stat_result, "st_file_attributes", 0) & _WINDOWS_REPARSE_POINT
    )


def _assert_plain_directory_ancestors(path: Path) -> Path:
    current = _lexical_absolute(path)
    while True:
        try:
            current_stat = os.lstat(current)
        except FileNotFoundError:
            pass
        else:
            if _is_reparse(current_stat):
                raise RuntimeError(
                    f"refusing a test runtime root through a reparse point: {current}"
                )
            if not stat.S_ISDIR(current_stat.st_mode):
                raise RuntimeError(f"test runtime ancestor is not a directory: {current}")
        if current.parent == current:
            return _lexical_absolute(path)
        current = current.parent


def _assert_plain_directory_tree(path: Path) -> None:
    for entry in os.scandir(path):
        entry_stat = entry.stat(follow_symlinks=False)
        if _is_reparse(entry_stat):
            raise RuntimeError(f"refusing to traverse a test runtime reparse point: {entry.path}")
        if stat.S_ISDIR(entry_stat.st_mode):
            _assert_plain_directory_tree(Path(entry.path))


def _try_lock_runtime_file(handle) -> bool:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                raise
            return False
        return True

    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno not in {errno.EACCES, errno.EAGAIN}:
            raise
        return False
    return True


def _unlock_runtime_file(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def host_runtime_lease() -> Iterator[None]:
    """Serialize shared PostgreSQL and runtime cleanup across local worktrees."""
    _assert_plain_directory_ancestors(_RUNTIME_LOCK_PATH.parent)
    _RUNTIME_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    _assert_plain_directory_ancestors(_RUNTIME_LOCK_PATH.parent)
    with _RUNTIME_LOCK_PATH.open("a+b", buffering=0) as handle:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"\0")
            handle.flush()
            os.fsync(handle.fileno())
        deadline = time.monotonic() + _RUNTIME_LOCK_TIMEOUT_SECONDS
        while not _try_lock_runtime_file(handle):
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "another pytest session owns the shared test PostgreSQL runtime"
                )
            time.sleep(0.1)
        try:
            yield
        finally:
            _unlock_runtime_file(handle)


def _remove_owned_runtime(path: Path, *, root: Path) -> None:
    target = _lexical_absolute(path)
    expected_root = _assert_plain_directory_ancestors(root)
    if not _same_path(target.parent, expected_root):
        raise RuntimeError(f"refusing to remove test runtime outside {expected_root}: {target}")
    try:
        target_stat = os.lstat(target)
    except FileNotFoundError:
        return
    if _is_reparse(target_stat):
        raise RuntimeError(f"refusing to remove a test runtime reparse point: {target}")
    if not stat.S_ISDIR(target_stat.st_mode):
        raise RuntimeError(f"test runtime is not a directory: {target}")
    if os.name == "nt":
        from tests._infra.windows_tree import remove_tree_exact

        remove_tree_exact(target)
    else:
        _assert_plain_directory_tree(target)
        if not shutil.rmtree.avoids_symlink_attacks:
            raise RuntimeError("test runtime deletion requires fd-based symlink protection")
        try:
            shutil.rmtree(target)
        except FileNotFoundError:
            return
    if os.path.lexists(target):
        raise RuntimeError(f"test runtime still exists after cleanup: {target}")


def cleanup_test_runtime(test_run_id: str) -> None:
    if _TEST_RUN_ID.fullmatch(test_run_id) is None:
        raise ValueError(f"invalid test runtime id: {test_run_id!r}")
    _remove_owned_runtime(
        _UPLOAD_RUNTIME_ROOT / f"pytest_test_{test_run_id}",
        root=_UPLOAD_RUNTIME_ROOT,
    )
    _remove_owned_runtime(_DATA_RUNTIME_ROOT / test_run_id, root=_DATA_RUNTIME_ROOT)


def _discover_runtime_ids() -> set[str]:
    runtime_ids: set[str] = set()
    for root, prefix in (
        (_UPLOAD_RUNTIME_ROOT, "pytest_test_"),
        (_DATA_RUNTIME_ROOT, ""),
    ):
        if not root.exists():
            continue
        _assert_plain_directory_ancestors(root)
        for candidate in os.scandir(root):
            if not candidate.name.startswith(prefix):
                continue
            runtime_id = candidate.name.removeprefix(prefix)
            if _TEST_RUN_ID.fullmatch(runtime_id) is not None:
                runtime_ids.add(runtime_id)
    return runtime_ids


def cleanup_orphan_test_runtimes() -> tuple[str, ...]:
    """Remove valid test-only runtime roots while the cluster lease is held."""
    runtime_ids = tuple(sorted(_discover_runtime_ids()))
    for runtime_id in runtime_ids:
        cleanup_test_runtime(runtime_id)
    return runtime_ids


def _cleanup_test_files() -> None:
    cleanup_test_runtime(TEST_RUN_ID)


def reset_db_state() -> None:
    """Drop & recreate schema, run init_db (migrations + seed)."""
    reset_public_schema(engine)
    _cleanup_test_files()
    init_db()


def cleanup_runtime() -> None:
    """Dispose the engine and clear the test upload dir. Session-end hook."""
    engine.dispose()
    _cleanup_test_files()


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
    ``@pytest.mark.real_db`` at the owning test.

    SessionLocal is restored to its engine binding BEFORE the rollback so a
    rollback hiccup can't leave a later test bound to a closed connection.
    """
    from app.database import SessionLocal

    # The DB rollback below undoes row writes, but saved upload files live on
    # disk outside any transaction. Clear the upload dir so one test's saved
    # images don't leak into the next (the rolled-back transaction can't reclaim
    # files written during the test).
    _cleanup_test_files()
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
