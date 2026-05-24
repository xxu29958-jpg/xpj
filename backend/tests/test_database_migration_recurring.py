"""Recurring items table migration to tenant-scoped indexes + constraints."""
from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import text

import app.database as database
from app.database import engine, init_db
from tests._infra.migration_helpers import (
    indexes,
    reset_empty_database,
    table_columns,
)


def test_legacy_recurring_items_migrate_to_tenant_indexes_and_constraints() -> None:
    reset_empty_database()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE recurring_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    merchant_key VARCHAR(255) NOT NULL,
                    merchant_name VARCHAR(255) NOT NULL,
                    baseline_amount_cents INTEGER NOT NULL,
                    last_amount_cents INTEGER NOT NULL,
                    last_seen_at DATETIME,
                    next_expected_date DATE,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO recurring_items (
                    merchant_key, merchant_name, baseline_amount_cents,
                    last_amount_cents, last_seen_at, next_expected_date,
                    created_at, updated_at
                )
                VALUES (
                    'netflix', 'Netflix', 6800, 6800,
                    '2026-05-01 00:00:00', '2026-06-01',
                    '2026-05-01 00:00:00', '2026-05-01 00:00:00'
                )
                """
            )
        )

    database.reset_sqlite_backup_state(done=True)
    try:
        init_db()

        assert {"public_id", "tenant_id", "frequency", "status", "source"}.issubset(
            table_columns("recurring_items")
        )
        assert "uq_recurring_items_tenant_merchant_frequency" in indexes("recurring_items")
        assert "ix_recurring_items_tenant_status_next" in indexes("recurring_items")
        with engine.begin() as connection:
            row = connection.execute(
                text("SELECT tenant_id, frequency, status, public_id FROM recurring_items WHERE id = 1")
            ).mappings().one()
        assert row["tenant_id"] == "owner"
        assert row["frequency"] == "monthly"
        assert row["status"] == "active"
        UUID(str(row["public_id"]))
    finally:
        database.reset_sqlite_backup_state(done=False)
        reset_empty_database()


def test_legacy_recurring_duplicate_scope_fails_before_unique_index() -> None:
    reset_empty_database()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE recurring_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id VARCHAR(64) NOT NULL,
                    merchant_key VARCHAR(255) NOT NULL,
                    merchant_name VARCHAR(255) NOT NULL,
                    frequency VARCHAR(32) NOT NULL,
                    status VARCHAR(32) NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO recurring_items
                    (tenant_id, merchant_key, merchant_name, frequency, status)
                VALUES
                    ('owner', 'netflix', 'Netflix', 'monthly', 'active'),
                    ('owner', 'netflix', 'Netflix', 'monthly', 'archived')
                """
            )
        )

    database.reset_sqlite_backup_state(done=True)
    try:
        with pytest.raises(RuntimeError, match="recurring_items"):
            init_db()
    finally:
        database.reset_sqlite_backup_state(done=False)
        reset_empty_database()
