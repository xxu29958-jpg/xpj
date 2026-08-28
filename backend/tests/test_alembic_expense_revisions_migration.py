"""PostgreSQL round-trip for the confirmed Expense revision schema."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text

from app.database import SessionLocal, engine
from app.services.currency_binding_service import resolve_write_capability
from tests._infra.alembic_runtime import reset_public_schema, run_alembic_for_test

pytestmark = pytest.mark.real_db

_HEAD = "20260828_0001"
_PARENT = "20260821_0001"
_TABLE = "expense_revisions"
_COLUMN = "fact_revision"
_CHECK = "ck_expenses_fact_revision_nonnegative"


def _cfg():
    from alembic.config import Config

    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "migrations"))
    return cfg


def _run(action, *args) -> None:
    run_alembic_for_test(engine, _cfg(), action, *args)


def _drop_alembic_version() -> None:
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))


def _assert_revision_schema_present() -> None:
    inspector = inspect(engine)
    assert _TABLE in inspector.get_table_names()
    assert _COLUMN in {column["name"] for column in inspector.get_columns("expenses")}
    assert _CHECK in {
        check["name"] for check in inspector.get_check_constraints("expenses")
    }
    assert "response_body" in {
        column["name"] for column in inspector.get_columns("api_idempotency_keys")
    }


def _downgrade_to_parent(command) -> None:
    _run(command.stamp, _HEAD)
    _run(command.downgrade, _PARENT)
    inspector = inspect(engine)
    assert _TABLE not in inspector.get_table_names()
    assert _COLUMN not in {
        column["name"] for column in inspector.get_columns("expenses")
    }


def _seed_legacy_confirmed_expense() -> int:
    confirmed_at = datetime(2026, 8, 20, 8, 30, tzinfo=UTC)
    with SessionLocal.begin() as db:
        resolve_write_capability(db)
        account_id = db.execute(
            text(
                "INSERT INTO accounts (public_id, display_name, created_at) "
                "VALUES (:public_id, '迁移用户', :created_at) RETURNING id"
            ),
            {"public_id": str(uuid4()), "created_at": confirmed_at},
        ).scalar_one()
        db.execute(
            text(
                "INSERT INTO ledgers (ledger_id, name, owner_account_id, created_at) "
                "VALUES ('migration-ledger', '迁移账本', :owner_account_id, :created_at)"
            ),
            {"owner_account_id": account_id, "created_at": confirmed_at},
        )
        return db.execute(
            text(
                "INSERT INTO expenses "
                "(public_id, tenant_id, amount_cents, home_currency_code, "
                "original_currency_code, original_amount_minor, exchange_rate_to_cny, "
                "exchange_rate_date, exchange_rate_source, fx_status, merchant, "
                "category, note, source, duplicate_status, status, expense_time, "
                "created_at, updated_at, row_version, confirmed_at, items_sum_status) "
                "VALUES (:public_id, 'migration-ledger', 1880, 'CNY', 'CNY', 1880, "
                "1, '2026-08-20', 'base', 'ready', '迁移前商家', '餐饮', '', "
                "'migration-test', 'none', 'confirmed', :expense_time, :created_at, "
                ":updated_at, 7, :confirmed_at, 'no_items') RETURNING id"
            ),
            {
                "public_id": str(uuid4()),
                "expense_time": confirmed_at,
                "created_at": confirmed_at,
                "updated_at": confirmed_at,
                "confirmed_at": confirmed_at,
            },
        ).scalar_one()


def _assert_legacy_backfill(expense_id: int) -> None:
    _assert_revision_schema_present()
    with engine.connect() as connection:
        projection = connection.execute(
            text("SELECT fact_revision FROM expenses WHERE id = :id"), {"id": expense_id}
        ).one()
        baseline = connection.execute(
            text(
                "SELECT revision_number, change_kind, before_snapshot, "
                "after_snapshot, resulting_row_version "
                "FROM expense_revisions WHERE expense_id = :id"
            ),
            {"id": expense_id},
        ).one()
    assert projection.fact_revision == 1
    assert baseline.revision_number == 1
    assert baseline.change_kind == "confirmed"
    assert baseline.before_snapshot is None
    assert baseline.after_snapshot["merchant"] == "迁移前商家"
    assert baseline.resulting_row_version == 7


def _dataset_authority_revision() -> str:
    with engine.connect() as connection:
        return connection.scalar(
            text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1")
        )


def test_expense_revision_migration_keeps_dataset_authority_aligned() -> None:
    from alembic import command

    reset_public_schema(engine)
    _drop_alembic_version()
    try:
        _run(command.upgrade, _PARENT)
        assert _dataset_authority_revision() == _PARENT
        _run(command.upgrade, _HEAD)
        assert _dataset_authority_revision() == _HEAD
        _run(command.downgrade, _PARENT)
        assert _dataset_authority_revision() == _PARENT
        _run(command.upgrade, _HEAD)
        assert _dataset_authority_revision() == _HEAD
    finally:
        reset_public_schema(engine)
        _drop_alembic_version()


def test_expense_revision_schema_round_trips_on_postgres() -> None:
    from alembic import command

    reset_public_schema(engine)
    _drop_alembic_version()
    try:
        _run(command.upgrade, _PARENT)
        legacy_expense_id = _seed_legacy_confirmed_expense()
        _run(command.upgrade, "head")
        _assert_legacy_backfill(legacy_expense_id)
    finally:
        reset_public_schema(engine)
        _drop_alembic_version()


def test_expense_revision_migration_backfills_historically_confirmed_rejected_row() -> None:
    from alembic import command

    reset_public_schema(engine)
    _drop_alembic_version()
    try:
        _run(command.upgrade, _PARENT)
        legacy_expense_id = _seed_legacy_confirmed_expense()
        rejected_at = datetime(2026, 8, 20, 8, 35, tzinfo=UTC)
        with SessionLocal.begin() as db:
            resolve_write_capability(db)
            db.execute(
                text(
                    "UPDATE expenses SET status = 'rejected', rejected_at = :rejected_at "
                    "WHERE id = :expense_id"
                ),
                {"expense_id": legacy_expense_id, "rejected_at": rejected_at},
            )

        _run(command.upgrade, _HEAD)
        _assert_legacy_backfill(legacy_expense_id)
    finally:
        reset_public_schema(engine)
        _drop_alembic_version()


def test_expense_revision_migration_refuses_downgrade_that_would_erase_history() -> None:
    from alembic import command

    reset_public_schema(engine)
    _drop_alembic_version()
    try:
        _run(command.upgrade, _PARENT)
        legacy_expense_id = _seed_legacy_confirmed_expense()
        _run(command.upgrade, _HEAD)

        with pytest.raises(RuntimeError, match="financial history"):
            _run(command.downgrade, _PARENT)

        assert _dataset_authority_revision() == _HEAD
        _assert_legacy_backfill(legacy_expense_id)
    finally:
        reset_public_schema(engine)
        _drop_alembic_version()
