"""Migrations for budgets, tags, and expense_tags join table — pure index creation."""

from __future__ import annotations

from sqlalchemy import text


def _migrate_budgets(connection) -> None:
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_budgets_tenant_month "
        "ON budgets (tenant_id, month)"
    ))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_budgets_tenant_month ON budgets (tenant_id, month)"))


def _migrate_tags(connection) -> None:
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_tags_id_tenant_id ON tags (id, tenant_id)"
    ))
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_tags_tenant_key ON tags (tenant_id, key)"
    ))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_tags_tenant_key ON tags (tenant_id, key)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_tags_tenant_name ON tags (tenant_id, name)"))


def _migrate_expense_tags(connection) -> None:
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_expense_tags_tenant_expense_tag "
        "ON expense_tags (tenant_id, expense_id, tag_id)"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_expense_tags_tenant_expense "
        "ON expense_tags (tenant_id, expense_id)"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_expense_tags_tenant_tag "
        "ON expense_tags (tenant_id, tag_id)"
    ))
