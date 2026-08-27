"""Seal PostgreSQL runtime access to the two fresh-install authority tables."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.database._managed_postgres_contract import RUNTIME_READ_ONLY_TABLES, RUNTIME_ROLE

_QUALIFIED_TABLES = ", ".join(f'public."{name}"' for name in RUNTIME_READ_ONLY_TABLES)
_TABLE_NAMES = ", ".join(f"'{name}'" for name in RUNTIME_READ_ONLY_TABLES)


def seal_runtime_authority_tables(connection: Connection) -> bool:
    connection.execute(
        text(
            "REVOKE INSERT, UPDATE, DELETE ON TABLE "
            f"{_QUALIFIED_TABLES} FROM {RUNTIME_ROLE}"
        )
    )
    return connection.scalar(
        text(
            "SELECT count(*) = 2 AND bool_and("
            f"has_table_privilege('{RUNTIME_ROLE}', relation.oid, 'SELECT') "
            f"AND NOT has_table_privilege('{RUNTIME_ROLE}', relation.oid, 'INSERT') "
            f"AND NOT has_table_privilege('{RUNTIME_ROLE}', relation.oid, 'UPDATE') "
            f"AND NOT has_table_privilege('{RUNTIME_ROLE}', relation.oid, 'DELETE')) "
            "FROM pg_catalog.pg_class AS relation "
            "JOIN pg_catalog.pg_namespace AS namespace "
            "ON namespace.oid = relation.relnamespace "
            "WHERE namespace.nspname = 'public' "
            f"AND relation.relname IN ({_TABLE_NAMES})"
        )
    ) is True


__all__ = ["seal_runtime_authority_tables"]
