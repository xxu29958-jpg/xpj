"""Legacy family role / ledger_members migration + role validation."""
from __future__ import annotations

import pytest
from sqlalchemy import text

import app.database as database
from app.database import engine, init_db
from tests._infra.migration_helpers import (
    indexes,
    reset_empty_database,
    table_create_sql,
)


def test_new_database_enforces_family_role_constraints() -> None:
    reset_empty_database()

    init_db()

    ledger_member_sql = table_create_sql("ledger_members")
    invitation_sql = table_create_sql("invitations")
    assert "ck_ledger_members_role_valid" in ledger_member_sql
    assert "uq_ledger_members_id_ledger_id" in ledger_member_sql
    assert "role IN ('owner', 'member', 'viewer')" in ledger_member_sql
    assert "ck_invitations_role_invitable" in invitation_sql
    assert "role IN ('member', 'viewer')" in invitation_sql


def test_legacy_ledger_member_parent_key_migrates_before_foreign_key_check() -> None:
    reset_empty_database()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE ledger_members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ledger_id VARCHAR(64) NOT NULL,
                    account_id INTEGER NOT NULL,
                    role VARCHAR(32) NOT NULL,
                    created_at DATETIME NOT NULL,
                    disabled_at DATETIME
                )
                """
            )
        )

    database.reset_sqlite_backup_state(done=True)
    try:
        init_db()

        assert "uq_ledger_members_id_ledger_id" in indexes("ledger_members")
        assert "uq_ledger_member_ledger_account" in indexes("ledger_members")
    finally:
        database.reset_sqlite_backup_state(done=False)
        reset_empty_database()


def test_legacy_duplicate_ledger_members_fail_before_unique_index() -> None:
    reset_empty_database()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE ledger_members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ledger_id VARCHAR(64) NOT NULL,
                    account_id INTEGER NOT NULL,
                    role VARCHAR(32) NOT NULL,
                    created_at DATETIME NOT NULL,
                    disabled_at DATETIME
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO ledger_members
                    (ledger_id, account_id, role, created_at)
                VALUES
                    ('owner', 1, 'member', '2026-05-04 08:00:00'),
                    ('owner', 1, 'viewer', '2026-05-04 08:00:00')
                """
            )
        )

    database.reset_sqlite_backup_state(done=True)
    try:
        with pytest.raises(RuntimeError, match="ledger_members"):
            init_db()
    finally:
        database.reset_sqlite_backup_state(done=False)
        reset_empty_database()


def test_legacy_database_with_invalid_family_roles_fails_startup() -> None:
    reset_empty_database()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE ledger_members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ledger_id VARCHAR(64) NOT NULL,
                    account_id INTEGER NOT NULL,
                    role VARCHAR(32) NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                "INSERT INTO ledger_members (ledger_id, account_id, role) "
                "VALUES ('owner', 1, 'admin')"
            )
        )

    database.reset_sqlite_backup_state(done=True)
    try:
        with pytest.raises(RuntimeError, match="ledger_members.role"):
            init_db()
    finally:
        database.reset_sqlite_backup_state(done=False)


@pytest.mark.parametrize(
    ("table_sql", "insert_sql", "message"),
    [
        (
            """
            CREATE TABLE ledger_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ledger_id VARCHAR(64) NOT NULL,
                account_id INTEGER NOT NULL,
                role VARCHAR(32)
            )
            """,
            "INSERT INTO ledger_members (ledger_id, account_id, role) VALUES ('owner', 1, NULL)",
            "ledger_members.role",
        ),
        (
            """
            CREATE TABLE invitations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ledger_id VARCHAR(64) NOT NULL,
                token_hash VARCHAR(64) NOT NULL,
                role VARCHAR(32)
            )
            """,
            "INSERT INTO invitations (ledger_id, token_hash, role) VALUES ('owner', 'hash', NULL)",
            "invitations.role",
        ),
    ],
)
def test_legacy_database_with_null_roles_fails_startup(
    table_sql: str,
    insert_sql: str,
    message: str,
) -> None:
    reset_empty_database()
    with engine.begin() as connection:
        connection.execute(text(table_sql))
        connection.execute(text(insert_sql))

    database.reset_sqlite_backup_state(done=True)
    try:
        with pytest.raises(RuntimeError, match=message):
            init_db()
    finally:
        database.reset_sqlite_backup_state(done=False)
        reset_empty_database()


def test_legacy_database_with_invalid_invitation_role_fails_startup() -> None:
    reset_empty_database()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE invitations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ledger_id VARCHAR(64) NOT NULL,
                    token_hash VARCHAR(64) NOT NULL,
                    role VARCHAR(32) NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                "INSERT INTO invitations (ledger_id, token_hash, role) "
                "VALUES ('owner', 'hash', 'owner')"
            )
        )

    database.reset_sqlite_backup_state(done=True)
    try:
        with pytest.raises(RuntimeError, match="invitations.role"):
            init_db()
    finally:
        database.reset_sqlite_backup_state(done=False)
