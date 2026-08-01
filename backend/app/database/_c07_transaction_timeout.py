"""Pre-BEGIN PostgreSQL transaction timeout discipline for C07.

PostgreSQL arms ``transaction_timeout`` when a transaction starts.  Changing
an already-active non-zero timeout inside that transaction does not restart or
shorten the timer.  C07 therefore sets the session value while the connection
is idle, starts exactly one transaction, and restores the caller's session
value before a pooled connection can be reused.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from psycopg import Error as PsycopgError
from sqlalchemy.exc import SQLAlchemyError


class C07TransactionTimeoutError(RuntimeError):
    """Raised when the pre-BEGIN timeout contract cannot be proven."""


def _timeout_setting(cursor: Any) -> int:
    cursor.execute(
        "SELECT setting, unit FROM pg_catalog.pg_settings "
        "WHERE name = 'transaction_timeout'"
    )
    row = cursor.fetchone()
    if (
        row is None
        or len(row) != 2
        or str(row[1]) != "ms"
        or not str(row[0]).isascii()
        or not str(row[0]).isdecimal()
    ):
        raise C07TransactionTimeoutError(
            "C07 requires PostgreSQL transaction_timeout in milliseconds"
        )
    return int(str(row[0]))


def _set_idle_session_timeout(connection: Any, timeout_ms: int) -> int:
    if connection.in_transaction():
        raise C07TransactionTimeoutError(
            "C07 transaction_timeout must be armed before BEGIN"
        )
    driver_connection = connection.connection.driver_connection
    original_autocommit = bool(driver_connection.autocommit)
    try:
        driver_connection.autocommit = True
        with driver_connection.cursor() as cursor:
            previous_ms = _timeout_setting(cursor)
            effective_ms = (
                timeout_ms
                if previous_ms == 0
                else min(previous_ms, timeout_ms)
            )
            cursor.execute(
                "SELECT set_config('transaction_timeout', %s, false)",
                (f"{effective_ms}ms",),
            )
            if _timeout_setting(cursor) != effective_ms:
                raise C07TransactionTimeoutError(
                    "C07 transaction_timeout pre-BEGIN arm was not effective"
                )
            return previous_ms
    finally:
        driver_connection.autocommit = original_autocommit


def _restore_idle_session_timeout(connection: Any, previous_ms: int) -> None:
    if connection.in_transaction():
        connection.rollback()
    driver_connection = connection.connection.driver_connection
    original_autocommit = bool(driver_connection.autocommit)
    try:
        driver_connection.autocommit = True
        with driver_connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('transaction_timeout', %s, false)",
                (f"{previous_ms}ms",),
            )
            if _timeout_setting(cursor) != previous_ms:
                raise C07TransactionTimeoutError(
                    "C07 transaction_timeout session value was not restored"
                )
    finally:
        driver_connection.autocommit = original_autocommit


@contextmanager
def c07_prearmed_transaction(
    connection: Any,
    *,
    timeout_ms: int,
) -> Iterator[Any]:
    """Run one transaction with an absolute timeout armed before ``BEGIN``.

    A tighter non-zero caller setting is preserved for the transaction and the
    original session value is restored afterwards.  If cleanup cannot be
    proven, the connection is invalidated so a pooled session cannot leak C07
    timeout state into unrelated work.
    """

    if (
        isinstance(timeout_ms, bool)
        or not isinstance(timeout_ms, int)
        or timeout_ms <= 0
    ):
        raise ValueError("C07 transaction timeout must be a positive integer")
    previous_ms = _set_idle_session_timeout(connection, timeout_ms)
    completed = False
    try:
        with connection.begin():
            yield connection
        completed = True
    finally:
        if not connection.invalidated and not connection.closed:
            try:
                _restore_idle_session_timeout(connection, previous_ms)
            except (C07TransactionTimeoutError, PsycopgError, SQLAlchemyError):
                connection.invalidate()
                if completed:
                    raise


__all__ = ["C07TransactionTimeoutError", "c07_prearmed_transaction"]
