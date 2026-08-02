"""Test-only Alembic execution support for revisions that cross C07.

The production C07 revision deliberately refuses an ordinary Alembic upgrade.
Real-PostgreSQL migration tests still need to drive the historical revision
chain, so this module supplies the smallest legal ceremony on the *existing
test connection*.  It does not patch or bypass the production migration.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

from app.database._c07_ceremony import (
    C07_CEREMONY_MODE_FRESH,
    C07_CEREMONY_MODE_MANAGED,
    C07_FRESH_CEREMONY_ID,
    _revision_includes_c07,
    set_c07_migration_context,
)
from app.database._c07_transaction_timeout import c07_prearmed_transaction

_C07_TEST_CEREMONY_ID = "d5148f80-1e6c-447d-b3bc-e3dc180d87b4"
_C07_TEST_TIMEOUT_MS = 20 * 60 * 1000
_ALEMBIC_CONNECTION_ATTRIBUTE = "connection"
_MISSING = object()


def _current_revision(connection: Connection) -> str | None:
    if "alembic_version" not in inspect(connection).get_table_names():
        return None
    value = connection.scalar(text("SELECT version_num FROM alembic_version"))
    return None if value is None else str(value)


def _fresh_database_has_no_business_rows(connection: Connection) -> bool:
    """Mirror the migration's fresh proof before selecting fresh mode."""

    tables = tuple(
        connection.scalars(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' "
                "AND tablename NOT IN "
                "('alembic_version', 'app_meta', 'schema_migrations') "
                "ORDER BY tablename"
            )
        )
    )
    quote = connection.dialect.identifier_preparer.quote_identifier
    return all(
        not bool(
            connection.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM "
                    f"{quote(str(table))} LIMIT 1)"
                )
            )
        )
        for table in tables
    )


def _set_test_c07_context(connection: Connection) -> None:
    current = _current_revision(connection)
    if current is None:
        if not _fresh_database_has_no_business_rows(connection):
            raise AssertionError(
                "C07 test fresh ceremony requires an unversioned database "
                "with no business rows; stamp the real source revision for "
                "a managed round-trip"
            )
        mode = C07_CEREMONY_MODE_FRESH
        ceremony_id = C07_FRESH_CEREMONY_ID
    else:
        mode = C07_CEREMONY_MODE_MANAGED
        ceremony_id = _C07_TEST_CEREMONY_ID
    set_c07_migration_context(
        connection,
        mode=mode,
        ceremony_id=ceremony_id,
    )


def _upgrade_targets_c07(
    action: Callable[..., Any],
    config: Config,
    args: tuple[object, ...],
) -> bool:
    if action is not command.upgrade or not args or not isinstance(args[0], str):
        return False
    return _revision_includes_c07(args[0], alembic_config=config)


def run_alembic_for_test(
    engine: Engine,
    config: Config,
    action: Callable[..., Any],
    *args: object,
) -> None:
    """Run one Alembic command and add C07 proof only when required."""

    crosses_c07 = _upgrade_targets_c07(action, config, args)
    previous_connection = config.attributes.get(
        _ALEMBIC_CONNECTION_ATTRIBUTE,
        _MISSING,
    )
    try:
        with engine.connect() as connection:
            transaction = (
                c07_prearmed_transaction(
                    connection,
                    timeout_ms=_C07_TEST_TIMEOUT_MS,
                )
                if crosses_c07
                else connection.begin()
            )
            with transaction:
                config.attributes[_ALEMBIC_CONNECTION_ATTRIBUTE] = connection
                if crosses_c07:
                    _set_test_c07_context(connection)
                action(config, *args)
    finally:
        if previous_connection is _MISSING:
            config.attributes.pop(_ALEMBIC_CONNECTION_ATTRIBUTE, None)
        else:
            config.attributes[_ALEMBIC_CONNECTION_ATTRIBUTE] = previous_connection


def reset_public_schema(engine: Engine) -> None:
    """Recover a throwaway PostgreSQL DB from any partial migration shape."""

    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))


__all__ = ["reset_public_schema", "run_alembic_for_test"]
