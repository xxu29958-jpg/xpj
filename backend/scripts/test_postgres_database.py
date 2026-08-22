"""Sealed connections and leases for dedicated PostgreSQL test databases."""

from __future__ import annotations

import hashlib
import ipaddress
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

if __package__:
    from scripts.test_postgres_contract import TEST_POSTGRES_CONTRACT
else:
    from test_postgres_contract import TEST_POSTGRES_CONTRACT

_DEDICATED_DATABASES = frozenset(
    {
        TEST_POSTGRES_CONTRACT.smoke_database,
        TEST_POSTGRES_CONTRACT.restore_database,
    }
)


def _require_loopback(value: str, *, field: str) -> None:
    if value.lower() == "localhost":
        return
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise RuntimeError(f"test PostgreSQL URL {field} must be loopback") from exc
    if not address.is_loopback:
        raise RuntimeError(f"test PostgreSQL URL {field} must be loopback")


def validated_test_postgres_conninfo(
    value: str,
    *,
    expected_database: str | None = None,
    expected_user: str | None = None,
) -> str:
    """Return libpq conninfo only after proving the complete test route."""
    parsed = make_url(value)
    if parsed.drivername != "postgresql+psycopg":
        raise RuntimeError("test PostgreSQL URL must use postgresql+psycopg")
    if expected_user is not None and parsed.username != expected_user:
        raise RuntimeError("test PostgreSQL URL reached an unexpected role")
    if parsed.password is not None:
        raise RuntimeError("test PostgreSQL URL must not embed a password")
    if parsed.host is None:
        raise RuntimeError("test PostgreSQL URL requires an explicit host")
    _require_loopback(parsed.host, field="host")
    if parsed.port is None:
        raise RuntimeError("test PostgreSQL URL requires an explicit port")
    TEST_POSTGRES_CONTRACT.require_allowed_host_port(parsed.port)
    if expected_database is not None and parsed.database != expected_database:
        raise RuntimeError(
            f"test PostgreSQL URL reached an unexpected database route: {parsed.database or '<missing>'}"
        )
    expected_query = {
        "connect_timeout",
        "hostaddr",
        "options",
        "require_auth",
        "sslmode",
    }
    if set(parsed.query) != expected_query:
        raise RuntimeError("test PostgreSQL URL query does not match the sealed route contract")
    hostaddr = parsed.query["hostaddr"]
    if not isinstance(hostaddr, str):
        raise RuntimeError("test PostgreSQL URL hostaddr must be singular")
    _require_loopback(hostaddr, field="hostaddr")
    if parsed.query["require_auth"] != "scram-sha-256":
        raise RuntimeError("test PostgreSQL URL must require SCRAM-SHA-256")
    if parsed.query["sslmode"] != "disable":
        raise RuntimeError("test PostgreSQL URL must disable TLS on the loopback route")
    if parsed.query["connect_timeout"] != "5":
        raise RuntimeError("test PostgreSQL URL must use the bounded connect timeout")
    if parsed.query["options"] != "-csearch_path=public,pg_catalog":
        raise RuntimeError("test PostgreSQL URL must seal the search path")
    return parsed.set(drivername="postgresql").render_as_string(hide_password=False)


def _database_lock_id(database: str) -> int:
    identity = f"{TEST_POSTGRES_CONTRACT.cluster_marker}:{database}".encode()
    return int.from_bytes(hashlib.sha256(identity).digest()[:8], "big", signed=True)


def _verify_dedicated_database(
    connection: psycopg.Connection,
    expected_database: str,
    cluster_identity: str,
) -> None:
    row = connection.execute(
        """
        SELECT current_database(), current_user,
               current_setting('is_superuser')::boolean,
               pg_catalog.pg_get_userbyid(datdba) = current_user,
               pg_catalog.shobj_description(oid, 'pg_database')
        FROM pg_catalog.pg_database
        WHERE datname = current_database()
        """
    ).fetchone()
    expected = (
        expected_database,
        TEST_POSTGRES_CONTRACT.application_role,
        False,
        True,
        cluster_identity,
    )
    if row != expected:
        raise RuntimeError("dedicated test database authority does not match its contract")


def _reset_public_schema(connection: psycopg.Connection) -> None:
    connection.execute("DROP SCHEMA IF EXISTS public CASCADE")
    connection.execute(
        sql.SQL("CREATE SCHEMA public AUTHORIZATION {}").format(sql.Identifier(TEST_POSTGRES_CONTRACT.application_role))
    )


@contextmanager
def dedicated_test_database_lease(
    database_url: str,
    *,
    expected_database: str,
    reset: bool,
    cluster_identity: str,
    passfile: str | None = None,
) -> Iterator[psycopg.Connection]:
    """Fail fast on competing runs and optionally rebuild the dedicated schema."""
    if expected_database not in _DEDICATED_DATABASES:
        raise RuntimeError("database is not a dedicated smoke or restore resource")
    cluster_identity = TEST_POSTGRES_CONTRACT.require_database_identity(cluster_identity)
    conninfo = validated_test_postgres_conninfo(
        database_url,
        expected_database=expected_database,
        expected_user=TEST_POSTGRES_CONTRACT.application_role,
    )
    connect_options = {"passfile": passfile} if passfile else {}
    with psycopg.connect(conninfo, autocommit=True, **connect_options) as connection:
        _verify_dedicated_database(connection, expected_database, cluster_identity)
        lock_id = _database_lock_id(expected_database)
        acquired = connection.execute(
            "SELECT pg_catalog.pg_try_advisory_lock(%s)",
            (lock_id,),
        ).fetchone()
        if acquired != (True,):
            raise RuntimeError("another process owns the dedicated test database")
        try:
            if reset:
                _reset_public_schema(connection)
            yield connection
        finally:
            released = connection.execute(
                "SELECT pg_catalog.pg_advisory_unlock(%s)",
                (lock_id,),
            ).fetchone()
            if released != (True,):
                raise RuntimeError("dedicated test database lease was lost")
