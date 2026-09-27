"""Capture only known current spending definitions and retain immutable history."""

from datetime import UTC, datetime
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
_PARENT = "20260927_0001"
_HEAD = "20260927_0002"


def test_upgrade_keeps_only_known_spending_baseline_and_protects_recorded_definitions():
    reset_schema()
    try:
        run_alembic(command.upgrade, _PARENT)
        seed_owner()
        with SessionLocal.begin() as db:
            activate_test_currency_authority(db, "JPY")
            db.execute(text("""INSERT INTO goals (public_id, tenant_id, name, goal_type, period, month,
                category, target_amount_cents, home_currency_code, status, row_version, created_at, updated_at,
                archived_at) VALUES (:key, 'owner', '既有交通目标', 'spending_limit', 'monthly', '2026-05',
                '交通', 1200, 'JPY', 'archived', 7, '2020-01-01T00:00:00Z', '2021-01-01T00:00:00Z',
                '2021-01-01T00:00:00Z')"""), {"key": str(uuid4())})
            db.execute(text("""INSERT INTO goals (public_id, tenant_id, name, goal_type, period, status,
                row_version, created_at, updated_at) VALUES (:key, 'owner', '原关联欠款目标', 'debt_repayment',
                'monthly', 'active', 4, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""), {"key": str(uuid4())})
        captured_after = datetime.now(UTC)
        run_alembic(command.upgrade, _HEAD)
        with engine.connect() as db:
            assert db.scalar(text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1")) == _HEAD
            rows = db.execute(text("SELECT row_version, change_kind, snapshot, actor_account_id, recorded_at "
                "FROM goal_revisions")).all()
            assert len(rows) == 1
            row = rows[0]
            assert (row.row_version, row.change_kind, row.actor_account_id) == (7, "baseline", None)
            assert row.recorded_at >= captured_after
            assert row.snapshot == {"name": "既有交通目标", "goal_type": "spending_limit", "period": "monthly",
                "month": "2026-05", "category": "交通", "target_amount_cents": 1200,
                "home_currency_code": "JPY", "status": "archived"}
            assert db.scalar(text("SELECT row_version FROM goals WHERE goal_type = 'debt_repayment'")) == 4
            assert db.scalar(text("SELECT updated_at FROM goals WHERE goal_type = 'spending_limit'")) == datetime(2021, 1, 1, tzinfo=UTC)
        with engine.begin() as db, pytest.raises(DBAPIError, match="goal revisions are immutable"):
            db.execute(text("UPDATE goal_revisions SET change_kind = 'edit'"))
        with engine.begin() as db, pytest.raises(DBAPIError, match="fk_goal_revision_goal_tenant"):
            db.execute(text("""INSERT INTO goal_revisions (tenant_id, goal_id, row_version, change_kind, snapshot, recorded_at)
                SELECT 'different-ledger', goal_id, 8, 'edit', snapshot, CURRENT_TIMESTAMP FROM goal_revisions"""))
        migration = import_module("migrations.versions.20260927_0002_spending_goal_revisions")
        with engine.begin() as db:
            migration.assert_postcondition(db)
            db.execute(text("ALTER TABLE goal_revisions DISABLE TRIGGER trg_goal_revision_immutable"))
            with pytest.raises(RuntimeError, match="immutability guard is missing"):
                migration.assert_postcondition(db)
            db.execute(text("ALTER TABLE goal_revisions ENABLE TRIGGER trg_goal_revision_immutable"))
            migration.assert_postcondition(db)
        run_alembic(command.downgrade, _PARENT)
        run_alembic(command.upgrade, _HEAD)
        with engine.begin() as db:
            db.execute(text("""INSERT INTO goal_revisions (tenant_id, goal_id, row_version, change_kind, snapshot, recorded_at)
                SELECT tenant_id, goal_id, 8, 'restore', snapshot, CURRENT_TIMESTAMP FROM goal_revisions"""))
        with pytest.raises(RuntimeError, match="cannot erase recorded goal revisions"):
            run_alembic(command.downgrade, _PARENT)
        with engine.connect() as db:
            assert db.scalar(text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1")) == _HEAD
            assert db.scalar(text("SELECT count(*) FROM goal_revisions")) == 2
    finally:
        reset_schema()
