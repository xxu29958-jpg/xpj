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
    finally:
        database.reset_sqlite_backup_state(done=False)
        reset_empty_database()
