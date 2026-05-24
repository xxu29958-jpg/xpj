"""Expense table / fx column / tags migration."""
from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import inspect, text

import app.database as database
from app.database import engine, init_db
from tests._infra.migration_helpers import (
    create_v01_expenses_table,
    expense_columns,
    fetch_expense,
    indexes,
    insert_legacy_expense,
    reset_empty_database,
)


@pytest.mark.parametrize(
    ("setup_sql", "message"),
    [
        (
            "UPDATE expenses SET amount_cents = -1",
            "expenses.amount_cents",
        ),
        (
            "UPDATE expenses SET status = 'archived'",
            "expenses.status",
        ),
        (
            "ALTER TABLE expenses ADD COLUMN duplicate_status VARCHAR(32) NOT NULL DEFAULT 'duplicate'",
            "expenses.duplicate_status",
        ),
        (
            "ALTER TABLE expenses ADD COLUMN original_amount_minor INTEGER DEFAULT -1",
            "expenses.original_amount_minor",
        ),
        (
            "ALTER TABLE expenses ADD COLUMN exchange_rate_to_cny NUMERIC(18, 8) DEFAULT 0",
            "expenses.exchange_rate_to_cny",
        ),
        (
            "ALTER TABLE expenses ADD COLUMN fx_status VARCHAR(32) DEFAULT 'stale'",
            "expenses.fx_status",
        ),
    ],
)
def test_legacy_database_with_invalid_expense_core_data_fails_startup(
    setup_sql: str,
    message: str,
) -> None:
    reset_empty_database()
    create_v01_expenses_table()
    insert_legacy_expense(amount_cents=3680, status="confirmed")
    with engine.begin() as connection:
        connection.execute(text(setup_sql))

    database.reset_sqlite_backup_state(done=True)
    try:
        with pytest.raises(RuntimeError, match=message):
            init_db()
    finally:
        database.reset_sqlite_backup_state(done=False)
        reset_empty_database()


@pytest.mark.parametrize(
    ("table_sql", "insert_sql", "message"),
    [
        (
            """
            CREATE TABLE budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id VARCHAR(64) NOT NULL,
                month VARCHAR(7) NOT NULL,
                total_amount_cents INTEGER NOT NULL DEFAULT 0
            )
            """,
            """
            INSERT INTO budgets (tenant_id, month, total_amount_cents)
            VALUES ('owner', '2026-05', 100), ('owner', '2026-05', 200)
            """,
            "budgets",
        ),
        (
            """
            CREATE TABLE merchant_aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id VARCHAR(64) NOT NULL,
                alias_key VARCHAR(255) NOT NULL,
                alias VARCHAR(255) NOT NULL,
                canonical_key VARCHAR(255) NOT NULL,
                canonical_merchant VARCHAR(255) NOT NULL
            )
            """,
            """
            INSERT INTO merchant_aliases
                (tenant_id, alias_key, alias, canonical_key, canonical_merchant)
            VALUES
                ('owner', 'starbucks', 'Starbucks', 'starbucks', 'Starbucks'),
                ('owner', 'starbucks', '星巴克', 'starbucks', 'Starbucks')
            """,
            "merchant_aliases",
        ),
    ],
)
def test_legacy_database_with_duplicate_unique_scope_rows_fails_startup(
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


def test_v01_schema_migrates_without_losing_expense_data() -> None:
    reset_empty_database()
    create_v01_expenses_table()
    expense_id = insert_legacy_expense(amount_cents=3680, status="confirmed")

    init_db()

    migrated = fetch_expense(expense_id)
    assert migrated["amount_cents"] == 3680
    assert migrated["merchant"] == "老商家"
    assert migrated["tenant_id"] == "owner"
    assert migrated["home_currency_code"] == "CNY"
    assert migrated["original_currency_code"] == "CNY"
    assert migrated["original_amount_minor"] == 3680
    assert str(migrated["exchange_rate_to_cny"]) in {"1", "1.0", "1.00000000"}
    assert migrated["exchange_rate_source"] == "base"
    assert str(migrated["exchange_rate_date"]).startswith("2026-05-04")
    assert migrated["fx_status"] == "ready"
    UUID(str(migrated["public_id"]))
    assert migrated["duplicate_status"] == "none"
    assert {"tenant_id", "public_id", "thumbnail_path", "tags", "image_deleted_at"}.issubset(expense_columns())
    assert "ix_expenses_public_id" in indexes("expenses")
    assert "ledger_audit_logs" in inspect(engine).get_table_names()


def test_legacy_foreign_expense_without_rate_migrates_to_fx_pending() -> None:
    reset_empty_database()
    create_v01_expenses_table()
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE expenses ADD COLUMN original_currency_code VARCHAR(3)"))
        connection.execute(text("ALTER TABLE expenses ADD COLUMN original_amount_minor INTEGER"))
        connection.execute(text("ALTER TABLE expenses ADD COLUMN exchange_rate_to_cny NUMERIC(18, 8)"))
        connection.execute(text("ALTER TABLE expenses ADD COLUMN exchange_rate_source VARCHAR(32)"))

    expense_id = insert_legacy_expense(amount_cents=12345, status="pending")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE expenses
                SET original_currency_code = 'USD',
                    original_amount_minor = 12345,
                    exchange_rate_to_cny = NULL,
                    exchange_rate_source = NULL
                WHERE id = :id
                """
            ),
            {"id": expense_id},
        )

    init_db()

    migrated = fetch_expense(expense_id)
    assert migrated["home_currency_code"] == "CNY"
    assert migrated["original_currency_code"] == "USD"
    assert migrated["original_amount_minor"] == 12345
    assert migrated["amount_cents"] is None
    assert migrated["exchange_rate_to_cny"] is None
    assert migrated["exchange_rate_source"] is None
    assert migrated["fx_status"] == "pending"


def test_legacy_expense_tags_backfill_normalized_relation_rows() -> None:
    reset_empty_database()
    create_v01_expenses_table()
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE expenses ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT 'owner'"))
        connection.execute(text("ALTER TABLE expenses ADD COLUMN tags TEXT"))
    expense_id = insert_legacy_expense(
        amount_cents=3680,
        status="confirmed",
        tenant_id="owner",
        tags="  真香，AI，真香 ",
    )

    init_db()

    migrated = fetch_expense(expense_id)
    assert migrated["tags"] == "真香, AI"
    with engine.begin() as connection:
        rows = connection.execute(
            text(
                "SELECT tags.name FROM tags "
                "JOIN expense_tags ON expense_tags.tag_id = tags.id "
                "WHERE tags.tenant_id = 'owner' AND expense_tags.expense_id = :expense_id "
                "ORDER BY tags.name"
            ),
            {"expense_id": expense_id},
        ).all()
    assert {str(row[0]) for row in rows} == {"真香", "AI"}
