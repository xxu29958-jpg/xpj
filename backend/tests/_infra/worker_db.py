"""Per-worker PostgreSQL database lifecycle for pytest-xdist.

The xdist controller gives every worker a stable id (``gw0``, ``gw1``, ...).
Each worker receives a database derived from the configured ``xpj_test`` base
database, so schema resets and committed rows cannot cross worker boundaries.
"""

from __future__ import annotations

import contextlib
import re
import secrets
from collections.abc import Iterator
from hashlib import sha256

import psycopg
from psycopg import sql
from sqlalchemy.engine import URL, make_url

from scripts.test_pg_contract import (
    admin_connection_args,
    validate_test_database_name,
    validate_test_database_url,
)

_WORKER_ID = re.compile(r"gw[0-9]+")
_WORKER_DATABASE_MARKER_PREFIX = "ticketbox:pytest-worker-database:v1"
_WORKER_LIFECYCLE_LOCK_KEY = int.from_bytes(
    sha256(b"ticketbox:pytest-worker-database-lifecycle:v1").digest()[:8],
    byteorder="big",
    signed=True,
)
_WORKER_LIFECYCLE_LOCK_TIMEOUT_MS = 15 * 60 * 1000


def new_worker_run_uid(worker_id: str | None) -> str | None:
    """Return an execution-owned nonce that xdist CLI options cannot reuse."""

    if worker_id is None:
        return None
    _validate_worker_id(worker_id)
    return secrets.token_hex(16)


def worker_database_url(base_url: str, worker_id: str, run_uid: str) -> str:
    """Return the isolated database URL for one xdist worker.

    The strict name checks are a safety boundary: this helper is allowed to
    drop and recreate only databases rooted at ``xpj_test``.
    """

    _validate_worker_id(worker_id)
    parsed = validate_test_database_url(base_url)
    base_name = parsed.database
    assert base_name is not None
    run_key = _run_key(run_uid)
    database_name = f"{base_name}_{run_key}_{worker_id}"
    if len(database_name.encode("utf-8")) > 63:
        raise ValueError("Derived PostgreSQL test database name exceeds 63 bytes")
    return parsed.set(database=database_name).render_as_string(hide_password=False)


@contextlib.contextmanager
def worker_database_lifecycle(
    database_url: str,
    *,
    worker_id: str,
    run_uid: str,
) -> Iterator[None]:
    """Own one worker database and reclaim only proven dead predecessors."""

    parsed = _validated_worker_url(
        database_url,
        worker_id=worker_id,
        run_uid=run_uid,
    )
    database_name = parsed.database
    assert database_name is not None
    base_name = _worker_base_name(database_name, worker_id, run_uid)
    lease = _prepare_worker_database(parsed, base_name=base_name)
    try:
        yield
    finally:
        lease.close()
        with _worker_lifecycle_guard(parsed) as connection:
            _drop_database(connection, database_name)


def _prepare_worker_database(
    parsed: URL,
    *,
    base_name: str,
) -> psycopg.Connection:
    database_name = parsed.database
    assert database_name is not None
    with _worker_lifecycle_guard(parsed) as connection:
        _reclaim_orphan_databases(connection, base_name=base_name)
        _drop_database(connection, database_name)
        _create_worker_database(
            connection,
            database_name=database_name,
            base_name=base_name,
        )
        try:
            lease = psycopg.connect(
                autocommit=True,
                **_worker_connection_args(parsed),
            )
            lease.execute(
                "SELECT set_config('idle_session_timeout', %s, false)",
                ("0",),
            )
        except psycopg.Error:
            _drop_database(connection, database_name)
            raise
    return lease


@contextlib.contextmanager
def _worker_lifecycle_guard(parsed: URL) -> Iterator[psycopg.Connection]:
    with psycopg.connect(
        autocommit=True,
        **admin_connection_args(parsed),
    ) as connection:
        connection.execute(
            "SELECT set_config('statement_timeout', %s, false)",
            (str(_WORKER_LIFECYCLE_LOCK_TIMEOUT_MS),),
        )
        connection.execute(
            "SELECT pg_advisory_lock(%s)",
            (_WORKER_LIFECYCLE_LOCK_KEY,),
        )
        try:
            yield connection
        finally:
            released = connection.execute(
                "SELECT pg_advisory_unlock(%s)",
                (_WORKER_LIFECYCLE_LOCK_KEY,),
            ).fetchone()
            if released != (True,):
                raise RuntimeError("Worker database lifecycle lock was not owned")


def _reclaim_orphan_databases(
    connection: psycopg.Connection,
    *,
    base_name: str,
) -> None:
    rows = connection.execute(
        """
        SELECT database.datname
        FROM pg_database AS database
        WHERE shobj_description(database.oid, 'pg_database') = %s
          AND NOT EXISTS (
              SELECT 1
              FROM pg_stat_activity AS activity
              WHERE activity.datname = database.datname
          )
        ORDER BY database.datname
        """,
        (_worker_database_marker(base_name),),
    ).fetchall()
    for (database_name,) in rows:
        if _is_owned_worker_database(base_name, database_name):
            _drop_database(connection, database_name)


def _drop_database(connection: psycopg.Connection, database_name: str) -> None:
    connection.execute(
        sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
            sql.Identifier(database_name)
        )
    )


def _create_worker_database(
    connection: psycopg.Connection,
    *,
    database_name: str,
    base_name: str,
) -> None:
    connection.execute(
        sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
    )
    connection.execute(
        sql.SQL("COMMENT ON DATABASE {} IS {}").format(
            sql.Identifier(database_name),
            sql.Literal(_worker_database_marker(base_name)),
        )
    )


def _worker_connection_args(parsed: URL) -> dict[str, object]:
    arguments = admin_connection_args(parsed)
    arguments["dbname"] = parsed.database
    return arguments


def _worker_database_marker(base_name: str) -> str:
    return f"{_WORKER_DATABASE_MARKER_PREFIX}:{base_name}"


def _is_owned_worker_database(base_name: str, database_name: object) -> bool:
    if not isinstance(database_name, str):
        return False
    pattern = re.compile(rf"{re.escape(base_name)}_[0-9a-f]{{16}}_gw[0-9]+")
    return pattern.fullmatch(database_name) is not None


def _validated_worker_url(
    database_url: str,
    *,
    worker_id: str,
    run_uid: str,
) -> URL:
    _validate_worker_id(worker_id)
    expected_suffix = f"_{_run_key(run_uid)}_{worker_id}"
    parsed = make_url(database_url)
    database_name = parsed.database or ""
    base_name = database_name.removesuffix(expected_suffix)
    if parsed.get_backend_name() != "postgresql" or base_name == database_name:
        raise ValueError(
            "Refusing lifecycle operation outside the current "
            "xpj_test_<run>_gwN database"
        )
    try:
        validate_test_database_name(base_name)
    except ValueError as exc:
        raise ValueError(
            "Refusing lifecycle operation outside the current "
            "xpj_test_<run>_gwN database"
        ) from exc
    return parsed


def _worker_base_name(database_name: str, worker_id: str, run_uid: str) -> str:
    return database_name.removesuffix(f"_{_run_key(run_uid)}_{worker_id}")


def _validate_worker_id(worker_id: str) -> None:
    if _WORKER_ID.fullmatch(worker_id) is None:
        raise ValueError(f"Invalid pytest-xdist worker id: {worker_id!r}")


def _run_key(run_uid: str) -> str:
    if not run_uid:
        raise ValueError("pytest-xdist run uid must not be empty")
    return sha256(run_uid.encode("utf-8")).hexdigest()[:16]
