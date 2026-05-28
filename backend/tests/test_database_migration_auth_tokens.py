"""auth_tokens table legacy schema migration."""
from __future__ import annotations

from sqlalchemy import text

import app.database as database
from app.database import engine, init_db
from tests._infra.migration_helpers import (
    indexes,
    reset_empty_database,
    table_columns,
)


def _create_legacy_auth_identity_tables_with_duplicate_active_tokens() -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE accounts (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    public_id VARCHAR(36),
                    display_name VARCHAR(120) NOT NULL,
                    identity_provider VARCHAR(64),
                    cloud_subject_id VARCHAR(255),
                    created_at DATETIME NOT NULL,
                    disabled_at DATETIME
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ledgers (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    ledger_id VARCHAR(64) NOT NULL,
                    name VARCHAR(120) NOT NULL,
                    owner_account_id INTEGER NOT NULL,
                    created_at DATETIME NOT NULL,
                    archived_at DATETIME
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE devices (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    public_id VARCHAR(36),
                    account_id INTEGER NOT NULL,
                    device_name VARCHAR(120) NOT NULL,
                    platform VARCHAR(32) NOT NULL,
                    created_at DATETIME NOT NULL,
                    last_seen_at DATETIME,
                    revoked_at DATETIME
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE auth_tokens (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    token_hash VARCHAR(64) NOT NULL,
                    account_id INTEGER NOT NULL,
                    device_id INTEGER NOT NULL,
                    ledger_id VARCHAR(64) NOT NULL,
                    scope VARCHAR(32) NOT NULL,
                    created_at DATETIME NOT NULL,
                    last_used_at DATETIME,
                    revoked_at DATETIME
                )
                """
            )
        )


def _seed_duplicate_active_auth_tokens() -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO accounts (id, public_id, display_name, created_at) "
                "VALUES (1, 'legacy-account', 'legacy', '2026-05-01 00:00:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO ledgers (id, ledger_id, name, owner_account_id, created_at) "
                "VALUES (1, 'owner', 'owner', 1, '2026-05-01 00:00:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO devices (id, public_id, account_id, device_name, platform, created_at) "
                "VALUES (1, 'legacy-device', 1, 'phone', 'android', '2026-05-01 00:00:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO auth_tokens "
                "(id, token_hash, account_id, device_id, ledger_id, scope, created_at, revoked_at) "
                "VALUES "
                "(1, 'hash-1', 1, 1, 'owner', 'app', '2026-05-01 00:00:00', NULL), "
                "(2, 'hash-2', 1, 1, 'owner', 'app', '2026-05-01 00:01:00', NULL)"
            )
        )


def test_legacy_auth_tokens_gain_expires_at_column_and_index() -> None:
    reset_empty_database()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE auth_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_hash VARCHAR(64) NOT NULL,
                    account_id INTEGER NOT NULL,
                    device_id INTEGER NOT NULL,
                    ledger_id VARCHAR(64) NOT NULL,
                    scope VARCHAR(32) NOT NULL,
                    created_at DATETIME NOT NULL,
                    last_used_at DATETIME,
                    revoked_at DATETIME
                )
                """
            )
        )

    database.reset_sqlite_backup_state(done=True)
    try:
        init_db()

        assert "expires_at" in table_columns("auth_tokens")
        assert "ix_auth_tokens_expires_at" in indexes("auth_tokens")
        assert "uq_auth_tokens_active_principal" in indexes("auth_tokens")
    finally:
        database.reset_sqlite_backup_state(done=False)
        reset_empty_database()


def test_legacy_active_auth_tokens_deduplicate_before_unique_index() -> None:
    reset_empty_database()
    _create_legacy_auth_identity_tables_with_duplicate_active_tokens()
    _seed_duplicate_active_auth_tokens()

    init_db()

    assert "expires_at" in table_columns("auth_tokens")
    assert "uq_auth_tokens_active_principal" in indexes("auth_tokens")
    with engine.begin() as connection:
        active_ids = list(
            connection.execute(
                text("SELECT id FROM auth_tokens WHERE revoked_at IS NULL ORDER BY id")
            ).scalars()
        )
        revoked_count = connection.execute(
            text("SELECT COUNT(*) FROM auth_tokens WHERE revoked_at IS NOT NULL")
        ).scalar_one()
    assert active_ids == [2]
    assert revoked_count == 1
