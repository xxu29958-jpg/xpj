"""public_id / tenant_id backfill on legacy rows + pre-v0.3 backup recreation guard."""
from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import text

from app.database import BACKEND_ROOT, engine, init_db
import app.database as database
from tests._infra.env import TEST_DB_PATH
from tests._infra.migration_helpers import (
    create_v01_expenses_table,
    fetch_expense,
    indexes,
    insert_legacy_expense,
    reset_empty_database,
    table_columns,
)


def test_missing_public_id_backfills_unique_values() -> None:
    reset_empty_database()
    create_v01_expenses_table()
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE expenses ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT 'owner'"))
        connection.execute(text("ALTER TABLE expenses ADD COLUMN public_id VARCHAR(36)"))
    first_id = insert_legacy_expense(public_id=None, tenant_id="owner")
    second_id = insert_legacy_expense(public_id="", tenant_id="owner")

    init_db()

    first = fetch_expense(first_id)
    second = fetch_expense(second_id)
    UUID(str(first["public_id"]))
    UUID(str(second["public_id"]))
    assert first["public_id"] != second["public_id"]
    assert "ix_expenses_public_id" in indexes("expenses")


def test_missing_tenant_id_backfills_owner_for_expenses_rules_and_duplicate_ignores() -> None:
    reset_empty_database()
    create_v01_expenses_table()
    expense_id = insert_legacy_expense()
    duplicate_target_id = insert_legacy_expense()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE category_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    keyword VARCHAR(255) NOT NULL,
                    category VARCHAR(64) NOT NULL,
                    enabled BOOLEAN NOT NULL DEFAULT 1,
                    priority INTEGER NOT NULL DEFAULT 100,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                "INSERT INTO category_rules (keyword, category, enabled, priority, created_at, updated_at) "
                "VALUES ('老规则', '生活', 1, 1, '2026-05-04 08:00:00', '2026-05-04 08:00:00')"
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE duplicate_ignores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    expense_id INTEGER NOT NULL,
                    duplicate_of_id INTEGER NOT NULL,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                "INSERT INTO duplicate_ignores (expense_id, duplicate_of_id, created_at) "
                "VALUES (:expense_id, :duplicate_target_id, '2026-05-04 08:00:00')"
            ),
            {"expense_id": expense_id, "duplicate_target_id": duplicate_target_id},
        )

    init_db()

    assert fetch_expense(expense_id)["tenant_id"] == "owner"
    with engine.begin() as connection:
        rule_tenant = connection.execute(text("SELECT tenant_id FROM category_rules WHERE keyword = '老规则'")).scalar_one()
        ignore = connection.execute(
            text("SELECT tenant_id, kind FROM duplicate_ignores WHERE expense_id = :expense_id"),
            {"expense_id": expense_id},
        ).mappings().one()
    assert rule_tenant == "owner"
    assert {
        "amount_min_cents",
        "amount_max_cents",
        "source_contains",
        "tag_contains",
    }.issubset(table_columns("category_rules"))
    assert "ix_category_rules_tenant_enabled_priority" in indexes("category_rules")
    assert ignore["tenant_id"] == "owner"
    assert ignore["kind"] == "manual"


@pytest.mark.file_backed_only
def test_pre_v03_backup_is_not_recreated_after_identity_migration() -> None:
    backup_dir = BACKEND_ROOT / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_pattern = f"{TEST_DB_PATH.stem}-pre-v0.3-*.db"
    for backup_file in backup_dir.glob(backup_pattern):
        backup_file.unlink()

    reset_empty_database()
    create_v01_expenses_table()
    insert_legacy_expense(amount_cents=3680, status="confirmed")

    try:
        database.reset_sqlite_backup_state(done=False)
        init_db()
        first_backups = sorted(backup_dir.glob(backup_pattern))
        assert len(first_backups) == 1

        database.reset_sqlite_backup_state(done=False)
        init_db()
        second_backups = sorted(backup_dir.glob(backup_pattern))
        assert second_backups == first_backups
    finally:
        for backup_file in backup_dir.glob(backup_pattern):
            backup_file.unlink()
