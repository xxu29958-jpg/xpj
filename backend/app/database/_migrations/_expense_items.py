"""ADR-0035 migration: rebuild expense_items to add kind enum + amount-by-kind CHECK."""

from __future__ import annotations

from sqlalchemy import text

from app.database._core import _sqlite_column_names


def _migrate_expense_items_for_kind(connection, table_names: set[str]) -> None:
    """ADR-0035: rebuild expense_items to add kind enum + new CHECK constraints.

    The legacy ``ck_expense_items_amount_non_negative`` CHECK blocks
    ``kind='discount'`` rows (negative amount). SQLite cannot drop a CHECK
    constraint in-place, so the standard cookbook is a table rebuild:

    1. CREATE TABLE expense_items_v1 with new shape
    2. INSERT ... SELECT to copy (defaulting kind='product')
    3. DROP TABLE expense_items
    4. RENAME expense_items_v1 → expense_items
    5. Recreate indexes

    Idempotent: returns early if the new ``kind`` column is already present.
    No other tables FK-reference ``expense_items``, so PRAGMA foreign_keys
    juggling is unnecessary.
    """
    if "expense_items" not in table_names:
        return
    existing_columns = _sqlite_column_names(connection, "expense_items")
    if "kind" in existing_columns:
        return

    connection.execute(text("""
        CREATE TABLE expense_items_v1 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            public_id VARCHAR(36) NOT NULL UNIQUE,
            tenant_id VARCHAR(64) NOT NULL,
            expense_id INTEGER NOT NULL,
            position INTEGER NOT NULL,
            kind VARCHAR(32) NOT NULL DEFAULT 'product',
            name VARCHAR(255) NOT NULL,
            quantity_text VARCHAR(64),
            unit_price_cents INTEGER,
            amount_cents INTEGER,
            category VARCHAR(64) NOT NULL DEFAULT '其他',
            raw_text TEXT,
            confidence FLOAT,
            is_ocr_draft BOOLEAN NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            CONSTRAINT ck_expense_items_position_non_negative CHECK (position >= 0),
            CONSTRAINT ck_expense_items_unit_price_non_negative CHECK (unit_price_cents IS NULL OR unit_price_cents >= 0),
            CONSTRAINT ck_expense_items_confidence CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
            CONSTRAINT ck_expense_items_kind_valid CHECK (kind IN ('product', 'discount', 'tax', 'service_fee')),
            CONSTRAINT ck_expense_items_amount_by_kind CHECK (
                (kind = 'product' AND (amount_cents IS NULL OR amount_cents >= 0))
                OR (kind = 'discount' AND (amount_cents IS NULL OR amount_cents <= 0))
                OR (kind IN ('tax', 'service_fee') AND (amount_cents IS NULL OR amount_cents >= 0))
            ),
            CONSTRAINT fk_expense_items_expense_tenant FOREIGN KEY (expense_id, tenant_id) REFERENCES expenses(id, tenant_id),
            CONSTRAINT uq_expense_items_tenant_expense_position UNIQUE (tenant_id, expense_id, position)
        )
    """))
    connection.execute(text("""
        INSERT INTO expense_items_v1 (
            id, public_id, tenant_id, expense_id, position, kind, name, quantity_text,
            unit_price_cents, amount_cents, category, raw_text, confidence, is_ocr_draft,
            created_at, updated_at
        )
        SELECT id, public_id, tenant_id, expense_id, position, 'product', name, quantity_text,
               unit_price_cents, amount_cents, category, raw_text, confidence, is_ocr_draft,
               created_at, updated_at
        FROM expense_items
    """))
    connection.execute(text("DROP TABLE expense_items"))
    connection.execute(text("ALTER TABLE expense_items_v1 RENAME TO expense_items"))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_expense_items_tenant_expense_position "
        "ON expense_items (tenant_id, expense_id, position)"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_expense_items_tenant_public_id "
        "ON expense_items (tenant_id, public_id)"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_expense_items_tenant_category "
        "ON expense_items (tenant_id, category)"
    ))
