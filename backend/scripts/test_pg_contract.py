"""Destructive PostgreSQL test-target and test-lane lock contracts."""

from __future__ import annotations

import contextlib
import os
import re
import sys
import threading
from collections.abc import Callable, Iterator, Mapping
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
_AUTHORITY_HEARTBEAT_SECONDS = 1.0
_AUTHORITY_WATCHDOG_JOIN_SECONDS = 5.0
_AUTHORITY_LOST_EXIT_CODE = 3


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
    if "dbname" in parsed.query:
        raise ValueError(
            "Test database URL must not define a dbname query parameter"
        )
    path_database = validate_test_database_name(parsed.database or "")
    resolved_database = _dialect_connection_args(parsed).get("dbname")
    if resolved_database != path_database:
        raise ValueError(
            "Test database URL must not override its xpj_test path database"
        )
    return parsed


def _abort_disposable_test_process(message: str) -> None:
    print(message, file=sys.stderr, flush=True)
    os._exit(_AUTHORITY_LOST_EXIT_CODE)


@contextlib.contextmanager
def authority_connection_watchdog(
    connection: psycopg.Connection,
    *,
    label: str,
    heartbeat_seconds: float = _AUTHORITY_HEARTBEAT_SECONDS,
    abort_process: Callable[[str], None] = _abort_disposable_test_process,
) -> Iterator[None]:
    """Abort a disposable pytest process if its authority session disappears."""

    stop = threading.Event()
    failures: list[BaseException] = []

    def monitor() -> None:
        while not stop.wait(heartbeat_seconds):
            try:
                connection.execute("SELECT 1", ()).fetchone()
            except psycopg.Error as exc:
                if stop.is_set():
                    return
                failures.append(exc)
                stop.set()
                abort_process(f"Lost PostgreSQL {label}; aborting this test process.")
                return

    thread = threading.Thread(
        target=monitor,
        name=f"postgres-{label}-watchdog",
        daemon=True,
    )
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=_AUTHORITY_WATCHDOG_JOIN_SECONDS)
        if thread.is_alive():
            message = f"PostgreSQL {label} watchdog did not stop; aborting this test process."
            abort_process(message)
            raise RuntimeError(message)
        if failures:
            raise RuntimeError(f"Lost PostgreSQL {label}") from failures[0]


@contextlib.contextmanager
def test_cluster_lock(
    environment: Mapping[str, str],
    *,
    exclusive: bool,
) -> Iterator[None]:
    """Coordinate isolated workers and destructive sessions on one PG cluster."""

    parsed = validate_test_database_url(configured_test_database_url(environment))
    lock_statement = (
        "SELECT pg_advisory_lock(%s)"
        if exclusive
        else "SELECT pg_advisory_lock_shared(%s)"
    )
    unlock_statement = (
        "SELECT pg_advisory_unlock(%s)"
        if exclusive
        else "SELECT pg_advisory_unlock_shared(%s)"
    )
    with psycopg.connect(
        autocommit=True,
        **admin_connection_args(parsed),
    ) as connection:
        connection.execute(
            "SELECT set_config('idle_session_timeout', %s, false)",
            ("0",),
        )
        connection.execute(
            "SELECT set_config('statement_timeout', %s, false)",
            (str(_STATEFUL_LOCK_TIMEOUT_MS),),
        )
        connection.execute(lock_statement, (_STATEFUL_LOCK_KEY,))
        try:
            mode = "exclusive" if exclusive else "shared"
            with authority_connection_watchdog(
                connection,
                label=f"test-lane {mode} lock",
            ):
                yield
        finally:
            released = connection.execute(
                unlock_statement,
                (_STATEFUL_LOCK_KEY,),
            ).fetchone()
            if released != (True,):
                raise RuntimeError(
                    f"PostgreSQL test-lane {mode} lock was not owned"
                )


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
