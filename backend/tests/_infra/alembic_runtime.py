"""Caller-owned Alembic execution support for real PostgreSQL tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.database._managed_postgres_migration_runtime import _prearmed_transaction

_TRANSACTION_TIMEOUT_MS = 20 * 60 * 1000
_ALEMBIC_CONNECTION_ATTRIBUTE = "connection"
_MISSING = object()


def run_alembic_for_test(
    engine: Engine,
    config: Config,
    action: Callable[..., Any],
    *args: object,
) -> None:
    """Run Alembic on the caller-owned connection and transaction."""

    previous_connection = config.attributes.get(
        _ALEMBIC_CONNECTION_ATTRIBUTE,
        _MISSING,
    )
    try:
        with engine.connect() as connection:
            transaction = (
                _prearmed_transaction(
                    connection,
                    timeout_ms=_TRANSACTION_TIMEOUT_MS,
                    access_mode="read_write",
                )
                if action is command.upgrade
                else connection.begin()
            )
            with transaction:
                config.attributes[_ALEMBIC_CONNECTION_ATTRIBUTE] = connection
                action(config, *args)
    finally:
        if previous_connection is _MISSING:
            config.attributes.pop(_ALEMBIC_CONNECTION_ATTRIBUTE, None)
        else:
            config.attributes[_ALEMBIC_CONNECTION_ATTRIBUTE] = previous_connection


def reset_public_schema(engine: Engine) -> None:
    """Recover a throwaway PostgreSQL database from any partial migration shape."""

    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))


__all__ = ["reset_public_schema", "run_alembic_for_test"]
