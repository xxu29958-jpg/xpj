"""Cross-ledger / tenant integrity invariants enforced at startup."""
from __future__ import annotations

import pytest
from sqlalchemy import text

import app.database as database
from app.database import SessionLocal, engine, init_db
from app.models import DuplicateIgnore, Expense
from tests._infra.migration_helpers import (
    insert_cross_ledger_duplicate_metadata,
    reset_empty_database,
)


def test_legacy_database_with_cross_ledger_expense_splits_fails_startup() -> None:
    reset_empty_database()
    init_db()

    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            owner_member_id = connection.execute(
                text("SELECT id FROM ledger_members WHERE ledger_id = 'owner' LIMIT 1")
            ).scalar_one()
            result = connection.execute(
                text(
                    """
                    INSERT INTO expenses (
                        tenant_id, public_id, amount_cents, merchant, category,
                        original_currency_code, original_amount_minor, exchange_rate_to_cny,
                        exchange_rate_date, exchange_rate_source, note, source, status,
                        duplicate_status, created_at, updated_at
                    )
                    VALUES (
                        'owner', '11111111-1111-1111-1111-111111111111',
                        1000, '坏数据', '其他', 'CNY', 1000, 1,
                        '2026-05-04', 'base', '', 'pytest', 'confirmed', 'none',
                        '2026-05-04 08:00:00', '2026-05-04 08:00:00'
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO expense_splits (
                        public_id, tenant_id, expense_id, member_id, position,
                        amount_cents, created_at, updated_at
                    )
                    VALUES (
                        '22222222-2222-2222-2222-222222222222',
                        'tester_1', :expense_id, :member_id, 0,
                        1000, '2026-05-04 08:00:00', '2026-05-04 08:00:00'
                    )
                    """
                ),
                {"expense_id": int(result.lastrowid), "member_id": owner_member_id},
            )
            connection.commit()
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")

        with pytest.raises(RuntimeError, match="expense_splits"):
            database.validate_sqlite_data_integrity()
    finally:
        reset_empty_database()


def test_legacy_duplicate_metadata_is_cleared_on_startup() -> None:
    reset_empty_database()
    init_db()

    try:
        owner_id, _tester_id = insert_cross_ledger_duplicate_metadata()

        init_db()

        with SessionLocal() as db:
            owner = db.get(Expense, owner_id)
            assert owner is not None
            assert owner.duplicate_status == "none"
            assert owner.duplicate_of_id is None
            assert owner.duplicate_reason is None
            assert db.query(DuplicateIgnore).count() == 0
    finally:
        reset_empty_database()


def test_sqlite_integrity_rejects_cross_ledger_duplicate_metadata() -> None:
    reset_empty_database()
    init_db()

    try:
        insert_cross_ledger_duplicate_metadata()

        with pytest.raises(RuntimeError, match="duplicate"):
            database.validate_sqlite_data_integrity()
    finally:
        reset_empty_database()


def test_sqlite_integrity_rejects_orphan_root_tenant_rows() -> None:
    reset_empty_database()
    init_db()

    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.execute(
                text(
                    """
                    INSERT INTO category_rules (
                        tenant_id, keyword, category, enabled, priority, created_at, updated_at
                    )
                    VALUES (
                        'missing_ledger', 'orphan', 'Other', 1, 1,
                        '2026-05-04 08:00:00', '2026-05-04 08:00:00'
                    )
                    """
                )
            )
            connection.commit()
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")

        with pytest.raises(RuntimeError, match="category_rules"):
            database.validate_sqlite_data_integrity()
    finally:
        reset_empty_database()


def test_sqlite_integrity_runs_foreign_key_check_for_identity_tables() -> None:
    reset_empty_database()
    init_db()

    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.execute(
                text(
                    """
                    INSERT INTO auth_tokens (
                        token_hash, account_id, device_id, ledger_id, scope, created_at
                    )
                    VALUES (
                        'bad-token-hash', 999999, 999999, 'owner', 'app',
                        '2026-05-04 08:00:00'
                    )
                    """
                )
            )
            connection.commit()
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")

        with pytest.raises(RuntimeError, match="foreign_key_check"):
            database.validate_sqlite_data_integrity()
    finally:
        reset_empty_database()


def test_legacy_database_with_invalid_tenant_id_fails_identity_seed() -> None:
    reset_empty_database()
    init_db()
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.execute(
            text(
                "UPDATE category_rules SET tenant_id = '../outside' "
                "WHERE id = (SELECT id FROM category_rules LIMIT 1)"
            )
        )
        connection.commit()
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")

    try:
        with pytest.raises(RuntimeError, match="tenant_id"):
            database.seed_identity_data()
    finally:
        reset_empty_database()
