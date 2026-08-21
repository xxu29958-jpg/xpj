"""Fail-closed cleanup for throwaway PostgreSQL databases and roles."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import psycopg
from psycopg import sql


def assert_database_schema_owners(
    connection: psycopg.Connection,
    *,
    expected_owner: str,
) -> None:
    owners = connection.execute(
        "SELECT pg_get_userbyid(database_record.datdba), "
        "pg_get_userbyid(namespace_record.nspowner) "
        "FROM pg_catalog.pg_database AS database_record "
        "JOIN pg_catalog.pg_namespace AS namespace_record "
        "ON namespace_record.nspname = 'public' "
        "WHERE database_record.datname = current_database()"
    ).fetchone()
    assert owners == (expected_owner, expected_owner)


def cleanup_postgres_topology(
    *,
    admin: psycopg.Connection,
    database: str,
    roles: Sequence[str],
) -> None:
    """Attempt every cleanup step and fail if any catalog object remains."""

    failures: list[BaseException] = []

    def attempt(action: Callable[[], object]) -> None:
        try:
            action()
        except BaseException as exc:  # noqa: BLE001 - collect all cleanup failures
            failures.append(exc)

    attempt(
        lambda: admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s OR usename = ANY(%s)",
            (database, list(roles)),
        )
    )
    attempt(
        lambda: admin.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                sql.Identifier(database)
            )
        )
    )
    attempt(
        lambda: admin.execute(
            sql.SQL("DROP ROLE IF EXISTS {}").format(
                sql.SQL(", ").join(sql.Identifier(role) for role in roles)
            )
        )
    )

    def assert_absent() -> None:
        database_exists = bool(
            admin.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s)",
                (database,),
            ).fetchone()[0]
        )
        remaining_roles = tuple(
            row[0]
            for row in admin.execute(
                "SELECT rolname FROM pg_catalog.pg_roles "
                "WHERE rolname = ANY(%s) ORDER BY rolname",
                (list(roles),),
            ).fetchall()
        )
        if database_exists or remaining_roles:
            raise AssertionError(
                "PostgreSQL cleanup left objects: "
                f"database={database_exists}, roles={remaining_roles!r}"
            )

    attempt(assert_absent)
    attempt(admin.close)
    if failures:
        raise BaseExceptionGroup("PostgreSQL topology cleanup failed", failures)


__all__ = ["assert_database_schema_owners", "cleanup_postgres_topology"]
