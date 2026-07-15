"""Per-worker PostgreSQL database lifecycle for pytest-xdist.

The xdist controller gives every worker a stable id (``gw0``, ``gw1``, ...).
Each worker receives a database derived from the configured ``xpj_test`` base
database, so schema resets and committed rows cannot cross worker boundaries.
"""

from __future__ import annotations

import re
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


def recreate_worker_database(
    database_url: str,
    *,
    worker_id: str,
    run_uid: str,
) -> None:
    """Drop any stale worker database and create a clean replacement."""

    parsed = _validated_worker_url(
        database_url,
        worker_id=worker_id,
        run_uid=run_uid,
    )
    database_name = parsed.database
    assert database_name is not None
    with psycopg.connect(autocommit=True, **admin_connection_args(parsed)) as connection:
        connection.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                sql.Identifier(database_name)
            )
        )
        connection.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
        )


def drop_worker_database(
    database_url: str,
    *,
    worker_id: str,
    run_uid: str,
) -> None:
    """Remove one xdist worker database after its engine has been disposed."""

    parsed = _validated_worker_url(
        database_url,
        worker_id=worker_id,
        run_uid=run_uid,
    )
    database_name = parsed.database
    assert database_name is not None
    with psycopg.connect(autocommit=True, **admin_connection_args(parsed)) as connection:
        connection.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                sql.Identifier(database_name)
            )
        )


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


def _validate_worker_id(worker_id: str) -> None:
    if _WORKER_ID.fullmatch(worker_id) is None:
        raise ValueError(f"Invalid pytest-xdist worker id: {worker_id!r}")


def _run_key(run_uid: str) -> str:
    if not run_uid:
        raise ValueError("pytest-xdist run uid must not be empty")
    return sha256(run_uid.encode("utf-8")).hexdigest()[:16]
