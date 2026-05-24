"""Migrations for recurring_items + goals.

Both delegate to their corresponding _validate helpers because creating
partial UNIQUE indexes on data that already violates them would fail at
the SQLite level.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import text

from app.database._core import _sqlite_column_names
from app.database._validate import (
    _validate_goal_unique_scopes,
    _validate_recurring_item_data,
)
from app.tenants import DEFAULT_TENANT_ID


def _migrate_recurring_items(connection, table_names: set[str]) -> None:
    columns = _sqlite_column_names(connection, "recurring_items")
    additions = {
        "public_id": "VARCHAR(36)",
        "tenant_id": f"VARCHAR(64) NOT NULL DEFAULT '{DEFAULT_TENANT_ID}'",
        "frequency": "VARCHAR(32) NOT NULL DEFAULT 'monthly'",
        "status": "VARCHAR(32) NOT NULL DEFAULT 'active'",
        "occurrence_count": "INTEGER NOT NULL DEFAULT 0",
        "source": "VARCHAR(32) NOT NULL DEFAULT 'candidate'",
        "paused_at": "DATETIME",
        "archived_at": "DATETIME",
    }
    for column_name, column_type in additions.items():
        if column_name not in columns:
            connection.execute(text(f"ALTER TABLE recurring_items ADD COLUMN {column_name} {column_type}"))
    connection.execute(
        text("UPDATE recurring_items SET tenant_id = :tenant_id WHERE tenant_id IS NULL OR tenant_id = ''"),
        {"tenant_id": DEFAULT_TENANT_ID},
    )
    connection.execute(text("UPDATE recurring_items SET frequency = 'monthly' WHERE frequency IS NULL OR frequency = ''"))
    connection.execute(text("UPDATE recurring_items SET status = 'active' WHERE status IS NULL OR status = ''"))
    public_id_rows = connection.execute(
        text("SELECT id FROM recurring_items WHERE public_id IS NULL OR public_id = ''")
    ).mappings()
    for row in public_id_rows:
        connection.execute(
            text("UPDATE recurring_items SET public_id = :public_id WHERE id = :id"),
            {"public_id": str(uuid4()), "id": row["id"]},
        )
    _validate_recurring_item_data(connection, table_names)
    columns = _sqlite_column_names(connection, "recurring_items")
    if "public_id" in columns:
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_recurring_items_public_id "
            "ON recurring_items (public_id)"
        ))
    if {"tenant_id", "merchant_key", "frequency"}.issubset(columns):
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_recurring_items_tenant_merchant_frequency "
            "ON recurring_items (tenant_id, merchant_key, frequency)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_recurring_items_tenant_merchant "
            "ON recurring_items (tenant_id, merchant_key)"
        ))
    if {"tenant_id", "status", "next_expected_date"}.issubset(columns):
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_recurring_items_tenant_status_next "
            "ON recurring_items (tenant_id, status, next_expected_date)"
        ))


def _migrate_goals(connection, table_names: set[str]) -> None:
    _validate_goal_unique_scopes(connection, table_names)
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_goals_active_total_scope "
        "ON goals (tenant_id, month, goal_type, period) "
        "WHERE status = 'active' AND category IS NULL"
    ))
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_goals_active_category_scope "
        "ON goals (tenant_id, month, goal_type, period, category) "
        "WHERE status = 'active' AND category IS NOT NULL"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_goals_tenant_month_status "
        "ON goals (tenant_id, month, status)"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_goals_tenant_category_month "
        "ON goals (tenant_id, category, month)"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_goals_tenant_public_id "
        "ON goals (tenant_id, public_id)"
    ))
