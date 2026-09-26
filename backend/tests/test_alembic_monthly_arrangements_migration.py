"""A new independent fact stays absent until saved; its history cannot be erased."""

from importlib import import_module

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.database import SessionLocal, engine
from tests._infra.c07_money_migration import reset_schema, run_alembic, seed_owner
from tests._infra.currency import activate_test_currency_authority

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]
_PARENT = "20260926_0001"
_HEAD = "20260927_0001"


def test_empty_upgrade_downgrade_and_saved_fact_history_guards():
    reset_schema()
    try:
        run_alembic(command.upgrade, _PARENT)
        seed_owner()
        run_alembic(command.upgrade, _HEAD)
        migration = import_module("migrations.versions.20260927_0001_monthly_arrangements")
        with engine.connect() as db:
            assert db.scalar(text("SELECT count(*) FROM monthly_arrangements")) == 0
            assert db.scalar(text("SELECT count(*) FROM monthly_arrangement_revisions")) == 0
            migration.assert_postcondition(db)
        run_alembic(command.downgrade, _PARENT)
        run_alembic(command.upgrade, _HEAD)
        with SessionLocal.begin() as db:
            activate_test_currency_authority(db, "JPY")
            db.execute(text("""INSERT INTO monthly_arrangements (tenant_id, month, home_currency_code,
                savings_target_cents, reserved_buffer_cents, row_version, created_at, updated_at)
                VALUES ('owner', '2026-09', 'JPY', 0, 300, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""))
            db.execute(text("""INSERT INTO monthly_arrangement_revisions (tenant_id, arrangement_id, row_version,
                home_currency_code, savings_target_cents, reserved_buffer_cents, recorded_at)
                SELECT tenant_id, id, row_version, home_currency_code, savings_target_cents, reserved_buffer_cents,
                updated_at FROM monthly_arrangements"""))
        for statement in ("UPDATE monthly_arrangement_revisions SET savings_target_cents = 1",
            "DELETE FROM monthly_arrangement_revisions"):
            with SessionLocal.begin() as db, pytest.raises(DBAPIError, match="immutable"):
                activate_test_currency_authority(db, "JPY")
                db.execute(text(statement))
        with SessionLocal.begin() as db, pytest.raises(DBAPIError,
            match="XPJ_CURRENCY_FENCE: truncate is forbidden for monthly_arrangement_revisions"):
            activate_test_currency_authority(db, "JPY")
            db.execute(text("TRUNCATE monthly_arrangement_revisions"))
        for statement in ("UPDATE monthly_arrangements SET home_currency_code = 'CNY'",
            "UPDATE monthly_arrangements SET savings_target_cents = -1",
            "UPDATE monthly_arrangements SET reserved_buffer_cents = 9000000000001",
            "INSERT INTO monthly_arrangement_revisions (tenant_id, arrangement_id, row_version, home_currency_code, "
            "savings_target_cents, reserved_buffer_cents, recorded_at) SELECT tenant_id, arrangement_id, row_version, "
            "home_currency_code, savings_target_cents, reserved_buffer_cents, recorded_at FROM monthly_arrangement_revisions"):
            with SessionLocal.begin() as db, pytest.raises(DBAPIError):
                activate_test_currency_authority(db, "JPY")
                db.execute(text(statement))
        with pytest.raises(RuntimeError, match="cannot erase saved"):
            run_alembic(command.downgrade, _PARENT)
        with engine.connect() as db:
            assert db.scalar(text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1")) == _HEAD
            assert db.execute(text("SELECT home_currency_code, savings_target_cents, reserved_buffer_cents FROM monthly_arrangements")).one() == ("JPY", 0, 300)
            assert db.execute(text("SELECT row_version, home_currency_code, savings_target_cents, reserved_buffer_cents "
                "FROM monthly_arrangement_revisions")).all() == [(1, "JPY", 0, 300)]
    finally:
        reset_schema()
