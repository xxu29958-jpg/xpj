"""expenses table migrations: columns + indexes + ADR-0029/0035 additions."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import text

from app.tenants import DEFAULT_TENANT_ID


def _expenses_required_columns(default_home: str, source_base: str, status_ready: str) -> dict[str, str]:
    return {
        "tenant_id": f"VARCHAR(64) NOT NULL DEFAULT '{DEFAULT_TENANT_ID}'",
        "public_id": "VARCHAR(36)",
        "thumbnail_path": "VARCHAR(500)",
        "duplicate_status": "VARCHAR(32) NOT NULL DEFAULT 'none'",
        "duplicate_of_id": "INTEGER",
        "duplicate_reason": "VARCHAR(500)",
        "tags": "TEXT",
        "value_score": "INTEGER",
        "regret_score": "INTEGER",
        "ocr_draft_fields": "TEXT",
        "draft_idempotency_key": "VARCHAR(128)",
        "home_currency_code": f"VARCHAR(3) NOT NULL DEFAULT '{default_home}'",
        "original_currency_code": f"VARCHAR(3) NOT NULL DEFAULT '{default_home}'",
        "original_amount_minor": "INTEGER",
        "exchange_rate_to_cny": "NUMERIC(18, 8)",
        "exchange_rate_date": "DATE",
        "exchange_rate_source": f"VARCHAR(32) DEFAULT '{source_base}'",
        "fx_status": f"VARCHAR(32) NOT NULL DEFAULT '{status_ready}'",
        "image_deleted_at": "DATETIME",
        "thumbnail_deleted_at": "DATETIME",
    }


def _migrate_expenses_columns(
    connection,
    *,
    existing_columns: set[str],
    default_home: str,
    source_base: str,
    status_ready: str,
    status_pending: str,
) -> None:
    """Add missing columns + backfill FX-related fields on expenses."""
    required = _expenses_required_columns(default_home, source_base, status_ready)
    for name, ddl in required.items():
        if name not in existing_columns:
            connection.execute(text(f"ALTER TABLE expenses ADD COLUMN {name} {ddl}"))

    connection.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_expenses_id_tenant_id "
            "ON expenses (id, tenant_id)"
        )
    )
    connection.execute(
        text("UPDATE expenses SET tenant_id = :tenant_id WHERE tenant_id IS NULL OR tenant_id = ''"),
        {"tenant_id": DEFAULT_TENANT_ID},
    )
    connection.execute(
        text("UPDATE expenses SET original_currency_code = :home WHERE original_currency_code IS NULL OR original_currency_code = ''"),
        {"home": default_home},
    )
    connection.execute(
        text("UPDATE expenses SET home_currency_code = :home WHERE home_currency_code IS NULL OR home_currency_code = ''"),
        {"home": default_home},
    )
    connection.execute(
        text(
            "UPDATE expenses SET original_amount_minor = amount_cents "
            "WHERE original_amount_minor IS NULL "
            "AND amount_cents IS NOT NULL "
            "AND original_currency_code = :home"
        ),
        {"home": default_home},
    )
    connection.execute(
        text(
            "UPDATE expenses SET exchange_rate_to_cny = 1 "
            "WHERE exchange_rate_to_cny IS NULL "
            "AND amount_cents IS NOT NULL "
            "AND original_currency_code = :home"
        ),
        {"home": default_home},
    )
    connection.execute(
        text(
            "UPDATE expenses SET amount_cents = NULL "
            "WHERE original_currency_code != :home "
            "AND original_amount_minor IS NOT NULL "
            "AND exchange_rate_to_cny IS NULL"
        ),
        {"home": default_home},
    )
    connection.execute(
        text(
            "UPDATE expenses SET exchange_rate_source = NULL "
            "WHERE original_currency_code != :home "
            "AND amount_cents IS NULL "
            "AND exchange_rate_to_cny IS NULL"
        ),
        {"home": default_home},
    )
    connection.execute(
        text(
            "UPDATE expenses SET exchange_rate_source = :source_base "
            "WHERE exchange_rate_source IS NULL AND original_currency_code = :home"
        ),
        {"source_base": source_base, "home": default_home},
    )
    connection.execute(
        text(
            "UPDATE expenses SET exchange_rate_date = date(COALESCE(expense_time, confirmed_at, created_at)) "
            "WHERE exchange_rate_date IS NULL AND amount_cents IS NOT NULL"
        )
    )
    connection.execute(
        text(
            "UPDATE expenses SET fx_status = :pending "
            "WHERE amount_cents IS NULL "
            "AND original_amount_minor IS NOT NULL "
            "AND original_currency_code != :home"
        ),
        {"home": default_home, "pending": status_pending},
    )
    connection.execute(
        text(
            "UPDATE expenses SET fx_status = :ready "
            "WHERE fx_status IS NULL OR fx_status = ''"
        ),
        {"ready": status_ready},
    )
    public_id_rows = connection.execute(
        text("SELECT id FROM expenses WHERE public_id IS NULL OR public_id = ''")
    ).mappings()
    for row in public_id_rows:
        connection.execute(
            text("UPDATE expenses SET public_id = :public_id WHERE id = :id"),
            {"public_id": str(uuid4()), "id": row["id"]},
        )


def _migrate_expenses_indexes(connection) -> None:
    """All non-unique + composite-unique indexes on expenses. Idempotent."""
    statements = (
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_expenses_public_id ON expenses (public_id)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_status_created_at ON expenses (status, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_category_status ON expenses (category, status)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_status_expense_time ON expenses (status, expense_time)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_status_confirmed_at ON expenses (status, confirmed_at)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_status_category_expense_time "
        "ON expenses (status, category, expense_time)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_status_category_confirmed_at "
        "ON expenses (status, category, confirmed_at)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_status_amount_merchant ON expenses (status, amount_cents, merchant)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_status_merchant_expense_time "
        "ON expenses (status, merchant, expense_time)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_status_merchant_confirmed_at "
        "ON expenses (status, merchant, confirmed_at)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_duplicate_status ON expenses (duplicate_status)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_duplicate_of_id ON expenses (duplicate_of_id)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_image_hash ON expenses (image_hash)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_tenant_status_created_at ON expenses (tenant_id, status, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_tenant_category_status ON expenses (tenant_id, category, status)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_tenant_status_expense_time ON expenses (tenant_id, status, expense_time)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_tenant_status_confirmed_at ON expenses (tenant_id, status, confirmed_at)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_tenant_status_category_expense_time "
        "ON expenses (tenant_id, status, category, expense_time)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_tenant_status_category_confirmed_at "
        "ON expenses (tenant_id, status, category, confirmed_at)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_tenant_status_amount_merchant "
        "ON expenses (tenant_id, status, amount_cents, merchant)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_tenant_status_merchant_expense_time "
        "ON expenses (tenant_id, status, merchant, expense_time)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_tenant_status_merchant_confirmed_at "
        "ON expenses (tenant_id, status, merchant, confirmed_at)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_expenses_tenant_draft_idempotency_key "
        "ON expenses (tenant_id, draft_idempotency_key)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_tenant_image_hash ON expenses (tenant_id, image_hash)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_tenant_duplicate_status ON expenses (tenant_id, duplicate_status)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_tenant_original_currency_date "
        "ON expenses (tenant_id, original_currency_code, exchange_rate_date)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_tenant_fx_status ON expenses (tenant_id, fx_status)",
    )
    for sql in statements:
        connection.execute(text(sql))


def _migrate_expenses_split_origin_invitation_id(
    connection, existing_expense_columns: set[str]
) -> None:
    """ADR-0029: add expenses.split_origin_invitation_id column.

    Pure additive column with default NULL. No backfill — existing rows
    are not from bill split (no invitation exists pre-v1.0).
    """
    if "split_origin_invitation_id" in existing_expense_columns:
        return
    connection.execute(text(
        "ALTER TABLE expenses ADD COLUMN split_origin_invitation_id VARCHAR(36)"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_expenses_split_origin_invitation_id "
        "ON expenses (split_origin_invitation_id)"
    ))


def _migrate_expenses_items_sum_status(connection, existing_expense_columns: set[str]) -> None:
    """ADR-0035: add expenses.items_sum_status column + backfill from items."""
    if "items_sum_status" in existing_expense_columns:
        return
    connection.execute(text(
        "ALTER TABLE expenses ADD COLUMN items_sum_status VARCHAR(32) NOT NULL DEFAULT 'no_items'"
    ))
    connection.execute(text("""
        UPDATE expenses
        SET items_sum_status = CASE
            WHEN (SELECT COUNT(*) FROM expense_items WHERE expense_items.expense_id = expenses.id) = 0
                THEN 'no_items'
            WHEN expenses.amount_cents IS NULL
                THEN 'matched'
            WHEN (
                SELECT SUM(amount_cents) FROM expense_items
                WHERE expense_items.expense_id = expenses.id
                  AND expense_items.amount_cents IS NOT NULL
            ) IS NULL
                THEN 'matched'
            WHEN expenses.amount_cents = (
                SELECT SUM(amount_cents) FROM expense_items
                WHERE expense_items.expense_id = expenses.id
                  AND expense_items.amount_cents IS NOT NULL
            )
                THEN 'matched'
            ELSE 'mismatch_known'
        END
    """))
