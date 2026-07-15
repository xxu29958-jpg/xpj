"""Per-worker PostgreSQL database lifecycle for pytest-xdist.

The xdist controller gives every worker a stable id (``gw0``, ``gw1``, ...).
Each worker receives a database derived from the configured ``xpj_test`` base
database, so schema resets and committed rows cannot cross worker boundaries.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from hashlib import sha256

import psycopg
from psycopg import sql
from sqlalchemy.engine import URL, make_url

_WORKER_ID = re.compile(r"gw[0-9]+")
_SAFE_TEST_DATABASE = re.compile(r"xpj_test(?:_[a-z0-9]+)*")
_DEFAULT_TEST_DATABASE_URL = "postgresql+psycopg://postgres@localhost:5438/xpj_test"


def configured_test_database_url(environment: Mapping[str, str]) -> str:
    """Resolve the base test URL, requiring confirmation for every override."""

    explicit = environment.get("XPJ_TEST_DATABASE_URL", "").strip()
    if not explicit:
        return _DEFAULT_TEST_DATABASE_URL
    if environment.get("XPJ_TEST_CLUSTER_CONFIRMED") != "1":
        raise RuntimeError(
            "XPJ_TEST_DATABASE_URL overrides require "
            "XPJ_TEST_CLUSTER_CONFIRMED=1"
        )
    return explicit


def worker_database_url(base_url: str, worker_id: str, run_uid: str) -> str:
    """Return the isolated database URL for one xdist worker.

    The strict name checks are a safety boundary: this helper is allowed to
    drop and recreate only databases rooted at ``xpj_test``.
    """

    _validate_worker_id(worker_id)
    parsed = make_url(base_url)
    if parsed.get_backend_name() != "postgresql":
        raise ValueError("Worker isolation requires a PostgreSQL test URL")
    base_name = parsed.database or ""
    if _SAFE_TEST_DATABASE.fullmatch(base_name) is None:
        raise ValueError(
            "Worker isolation may derive databases only from an xpj_test base"
        )
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
    with psycopg.connect(autocommit=True, **_admin_connection_args(parsed)) as connection:
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
    with psycopg.connect(autocommit=True, **_admin_connection_args(parsed)) as connection:
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
    if (
        parsed.get_backend_name() != "postgresql"
        or base_name == database_name
        or _SAFE_TEST_DATABASE.fullmatch(base_name) is None
    ):
        raise ValueError(
            "Refusing lifecycle operation outside the current "
            "xpj_test_<run>_gwN database"
        )
    return parsed


def _validate_worker_id(worker_id: str) -> None:
    if _WORKER_ID.fullmatch(worker_id) is None:
        raise ValueError(f"Invalid pytest-xdist worker id: {worker_id!r}")


def _run_key(run_uid: str) -> str:
    if not run_uid:
        raise ValueError("pytest-xdist run uid must not be empty")
    return sha256(run_uid.encode("utf-8")).hexdigest()[:16]


def _admin_connection_args(database_url: URL) -> dict[str, object]:
    query: Mapping[str, str | tuple[str, ...]] = database_url.query
    arguments: dict[str, object] = {
        key: value for key, value in query.items() if isinstance(value, str)
    }
    arguments.update(
        {
            "dbname": "postgres",
            "host": database_url.host or "localhost",
        }
    )
    if database_url.port is not None:
        arguments["port"] = database_url.port
    if database_url.username is not None:
        arguments["user"] = database_url.username
    if database_url.password is not None:
        arguments["password"] = database_url.password
    return arguments
