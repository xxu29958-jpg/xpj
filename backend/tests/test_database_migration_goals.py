"""goals table legacy duplicate-row protection."""
from __future__ import annotations

import pytest
from sqlalchemy import text

import app.database as database
from app.database import engine, init_db
from tests._infra.migration_helpers import reset_empty_database


def test_legacy_database_with_duplicate_active_goals_fails_before_unique_index() -> None:
    reset_empty_database()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE goals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id VARCHAR(64) NOT NULL,
                    month VARCHAR(7) NOT NULL,
                    goal_type VARCHAR(32) NOT NULL,
                    period VARCHAR(32) NOT NULL,
                    category VARCHAR(64),
                    status VARCHAR(32) NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                "INSERT INTO goals (tenant_id, month, goal_type, period, category, status) "
                "VALUES "
                "('owner', '2026-05', 'spending', 'monthly', NULL, 'active'), "
                "('owner', '2026-05', 'spending', 'monthly', NULL, 'active')"
            )
        )

    database.reset_sqlite_backup_state(done=True)
    try:
        with pytest.raises(RuntimeError, match="duplicate active total goals"):
            init_db()
    finally:
        database.reset_sqlite_backup_state(done=False)
        reset_empty_database()
