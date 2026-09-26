"""The existing snapshot is preserved honestly; recorded revisions cannot be erased."""

from importlib import import_module
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.database import SessionLocal, engine
from tests._infra.c07_money_migration import reset_schema, run_alembic, seed_owner
from tests._infra.currency import activate_test_currency_authority

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]
_PARENT = "20260920_0003"
_HEAD = "20260926_0001"


def test_budget_baseline_keeps_saved_currency_categories_and_archive_without_inventing_edits():
    reset_schema()
    try:
        run_alembic(command.upgrade, _PARENT)
        seed_owner()
        with SessionLocal.begin() as db:
            activate_test_currency_authority(db, "JPY")
            db.execute(text("""INSERT INTO budgets (public_id, tenant_id, month, home_currency_code,
                total_amount_cents, non_monthly_amount_cents, rollover_amount_cents, excluded_categories,
                row_version, created_at, updated_at, archived_at)
                VALUES (:key, 'owner', '2026-09', 'JPY', 1200, 100, -20, '["旅行"]', 4,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""), {"key": str(uuid4())})
            db.execute(text("""INSERT INTO budget_categories (public_id, tenant_id, month, category,
                amount_cents, created_at, updated_at) VALUES (:key, 'owner', '2026-09', '餐饮', 300,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""), {"key": str(uuid4())})
        run_alembic(command.upgrade, _HEAD)
        with engine.connect() as db:
            assert db.scalar(text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1")) == _HEAD
            version, kind, snapshot = db.execute(text("SELECT row_version, change_kind, snapshot FROM budget_revisions")).one()
            assert (version, kind) == (4, "baseline")
            assert snapshot == {"home_currency_code": "JPY", "total_amount_cents": 1200,
                "non_monthly_amount_cents": 100, "rollover_amount_cents": -20,
                "excluded_categories": ["旅行"], "archived": True,
                "category_budgets": [{"category": "餐饮", "amount_cents": 300}]}
        with engine.begin() as db, pytest.raises(DBAPIError, match="budget revisions are immutable"):
            db.execute(text("UPDATE budget_revisions SET change_kind = 'edit'"))
        migration = import_module("migrations.versions.20260926_0001_budget_revisions")
        with engine.begin() as db:
            migration.assert_postcondition(db)
            db.execute(text("ALTER TABLE budget_revisions DISABLE TRIGGER trg_budget_revision_immutable"))
            with pytest.raises(RuntimeError, match="immutability guard is missing"):
                migration.assert_postcondition(db)
            db.execute(text("ALTER TABLE budget_revisions ENABLE TRIGGER trg_budget_revision_immutable"))
            migration.assert_postcondition(db)
        run_alembic(command.downgrade, _PARENT)
        with engine.connect() as db:
            assert db.scalar(text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1")) == _PARENT
        run_alembic(command.upgrade, _HEAD)
        with engine.begin() as db:
            db.execute(text("""INSERT INTO budget_revisions (tenant_id, budget_id, row_version, change_kind, snapshot, recorded_at)
                SELECT tenant_id, budget_id, 5, 'restore', snapshot, CURRENT_TIMESTAMP FROM budget_revisions"""))
        with pytest.raises(RuntimeError, match="cannot erase recorded budget revisions"):
            run_alembic(command.downgrade, _PARENT)
        with engine.connect() as db:
            assert db.scalar(text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1")) == _HEAD
            assert db.scalar(text("SELECT count(*) FROM budget_revisions")) == 2
    finally:
        reset_schema()


def test_upgrade_keeps_tolerated_legacy_exclusions_readable_and_leaves_raw_rows_intact():
    cases = [("2026-01", "not json", []), ("2026-02", "{}", []),
        ("2026-03", "[1]", []), ("2026-04", '[" 吃饭 ", "餐饮", null, "交通"]', ["餐饮", "交通"])]
    reset_schema()
    try:
        run_alembic(command.upgrade, _PARENT)
        seed_owner()
        with SessionLocal.begin() as db:
            activate_test_currency_authority(db, "JPY")
            for month, raw, _ in cases:
                db.execute(text("""INSERT INTO budgets (public_id, tenant_id, month, home_currency_code,
                    total_amount_cents, non_monthly_amount_cents, rollover_amount_cents, excluded_categories,
                    row_version, created_at, updated_at)
                    VALUES (:key, 'owner', :month, 'JPY', 1200, 100, 0, :raw, 1,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""), {"key": str(uuid4()), "month": month, "raw": raw})
        run_alembic(command.upgrade, _HEAD)
        with engine.connect() as db:
            rows = db.execute(text("""SELECT b.month, b.excluded_categories, r.snapshot FROM budgets b
                JOIN budget_revisions r ON r.budget_id = b.id AND r.tenant_id = b.tenant_id ORDER BY b.month""")).all()
            assert [(row.month, row.excluded_categories, row.snapshot["excluded_categories"]) for row in rows] == cases
    finally:
        reset_schema()
