"""Destructive PostgreSQL test-target and stateful-lane contracts."""

from __future__ import annotations

import contextlib
import re
from collections.abc import Iterator, Mapping
from hashlib import sha256

import psycopg
from sqlalchemy.engine import URL, make_url

_SAFE_TEST_DATABASE = re.compile(r"xpj_test(?:_[a-z0-9]+)*")
_DEFAULT_TEST_DATABASE_URL = "postgresql+psycopg://postgres@localhost:5438/xpj_test"
_STATEFUL_LOCK_KEY = int.from_bytes(
    sha256(b"ticketbox:postgres-stateful-test-lane:v1").digest()[:8],
    byteorder="big",
    signed=True,
)
_STATEFUL_LOCK_TIMEOUT_MS = 15 * 60 * 1000


def configured_test_database_url(environment: Mapping[str, str]) -> str:
    """Resolve and validate the base test URL and any explicit override."""

    explicit = environment.get("XPJ_TEST_DATABASE_URL", "").strip()
    if not explicit:
        database_url = _DEFAULT_TEST_DATABASE_URL
    else:
        if environment.get("XPJ_TEST_CLUSTER_CONFIRMED") != "1":
            raise RuntimeError(
                "XPJ_TEST_DATABASE_URL overrides require "
                "XPJ_TEST_CLUSTER_CONFIRMED=1"
            )
        database_url = explicit
    validate_test_database_url(database_url)
    return database_url


def validate_test_database_name(database_name: str) -> str:
    """Require the complete destructive-test database naming contract."""

    if _SAFE_TEST_DATABASE.fullmatch(database_name) is None:
        raise ValueError("Test database must match the xpj_test base contract")
    return database_name


def validate_test_database_url(database_url: str | URL) -> URL:
    """Parse and validate one PostgreSQL test database URL."""

    parsed = make_url(database_url)
    if parsed.get_backend_name() != "postgresql":
        raise ValueError("Test database URL must use PostgreSQL")
    path_database = validate_test_database_name(parsed.database or "")
    resolved_database = _dialect_connection_args(parsed).get("dbname")
    if resolved_database != path_database:
        raise ValueError(
            "Test database URL must not override its xpj_test path database"
        )
    return parsed


@contextlib.contextmanager
def stateful_test_cluster_lock(environment: Mapping[str, str]) -> Iterator[None]:
    """Serialize stateful lanes across processes sharing one PG cluster."""

    parsed = validate_test_database_url(configured_test_database_url(environment))
    with psycopg.connect(
        autocommit=True,
        **admin_connection_args(parsed),
    ) as connection:
        connection.execute(
            "SELECT set_config('statement_timeout', %s, false)",
            (str(_STATEFUL_LOCK_TIMEOUT_MS),),
        )
        connection.execute("SELECT pg_advisory_lock(%s)", (_STATEFUL_LOCK_KEY,))
        try:
            yield
        finally:
            released = connection.execute(
                "SELECT pg_advisory_unlock(%s)",
                (_STATEFUL_LOCK_KEY,),
            ).fetchone()
            if released != (True,):
                raise RuntimeError("Stateful PostgreSQL test-lane lock was not owned")


def admin_connection_args(database_url: URL) -> dict[str, object]:
    """Resolve the exact engine target and replace only its database name."""

    parsed = validate_test_database_url(database_url)
    arguments = _dialect_connection_args(parsed)
    arguments["dbname"] = "postgres"
    return arguments


def _dialect_connection_args(database_url: URL) -> dict[str, object]:
    positional, keyword = database_url.get_dialect()().create_connect_args(
        database_url
    )
    if positional:
        raise ValueError("PostgreSQL test URLs must resolve without positional args")
    return dict(keyword)
