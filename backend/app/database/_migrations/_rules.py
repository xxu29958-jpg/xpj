"""Migrations for category rules + rule application history + merchant aliases."""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.tenants import DEFAULT_TENANT_ID


def _migrate_category_rules(connection) -> None:
    columns = {column["name"] for column in inspect(connection).get_columns("category_rules")}
    if "tenant_id" not in columns:
        connection.execute(
            text(f"ALTER TABLE category_rules ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT '{DEFAULT_TENANT_ID}'")
        )
    additions = {
        "amount_min_cents": "INTEGER",
        "amount_max_cents": "INTEGER",
        "source_contains": "VARCHAR(64)",
        "tag_contains": "VARCHAR(64)",
        # ADR-0038 undo: soft-delete marker. NULL = live; reads filter
        # ``deleted_at IS NULL``. Unlike merchant_aliases there is no unique
        # constraint to preserve, so a recreated rule never conflicts.
        "deleted_at": "DATETIME",
        # ADR-0041: keep the legacy migrator column-complete for row_version
        # (Alembic 20260603_0001 also adds it; both guarded, runs once).
        "row_version": "INTEGER NOT NULL DEFAULT 1",
    }
    for column_name, column_type in additions.items():
        if column_name not in columns:
            connection.execute(text(f"ALTER TABLE category_rules ADD COLUMN {column_name} {column_type}"))
    connection.execute(
        text("UPDATE category_rules SET tenant_id = :tenant_id WHERE tenant_id IS NULL OR tenant_id = ''"),
        {"tenant_id": DEFAULT_TENANT_ID},
    )
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_category_rules_tenant_priority_id "
        "ON category_rules (tenant_id, priority, id)"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_category_rules_tenant_enabled_priority "
        "ON category_rules (tenant_id, enabled, priority, id)"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_category_rules_tenant_deleted "
        "ON category_rules (tenant_id, deleted_at)"
    ))


def _migrate_rule_application_batches(connection) -> None:
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_rule_application_batches_id_tenant_id "
        "ON rule_application_batches (id, tenant_id)"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_rule_application_batches_tenant_created_at "
        "ON rule_application_batches (tenant_id, created_at)"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_rule_application_batches_tenant_status "
        "ON rule_application_batches (tenant_id, status)"
    ))


def _migrate_rule_application_changes(connection) -> None:
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_rule_application_changes_tenant_batch "
        "ON rule_application_changes (tenant_id, batch_id)"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_rule_application_changes_tenant_expense "
        "ON rule_application_changes (tenant_id, expense_id)"
    ))


def _migrate_merchant_aliases(connection) -> None:
    # ADR-0038 undo: additive soft-delete marker. NULL = live. The
    # (tenant_id, alias_key) unique constraint is intentionally left intact
    # (SQLite cannot drop a table constraint without a rebuild), so a
    # soft-deleted key stays reserved during its undo window — recreating it
    # returns 409 until undo or cleanup. Reads filter ``deleted_at IS NULL``.
    columns = {column["name"] for column in inspect(connection).get_columns("merchant_aliases")}
    if "deleted_at" not in columns:
        connection.execute(text("ALTER TABLE merchant_aliases ADD COLUMN deleted_at DATETIME"))
    # ADR-0041: row_version OCC column (Alembic 20260603_0001 also adds it).
    if "row_version" not in columns:
        connection.execute(
            text("ALTER TABLE merchant_aliases ADD COLUMN row_version INTEGER NOT NULL DEFAULT 1")
        )
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_merchant_aliases_tenant_deleted "
        "ON merchant_aliases (tenant_id, deleted_at)"
    ))
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_merchant_aliases_tenant_alias_key "
        "ON merchant_aliases (tenant_id, alias_key)"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_merchant_aliases_tenant_canonical "
        "ON merchant_aliases (tenant_id, canonical_key)"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_merchant_aliases_tenant_alias_key "
        "ON merchant_aliases (tenant_id, alias_key)"
    ))
