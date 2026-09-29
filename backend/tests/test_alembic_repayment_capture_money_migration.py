"""Preserve legacy record units and reject erasing newly captured originals."""

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
_PARENT = "20260928_0001"
_HEAD = "20260930_0001"


def test_capture_migration_preserves_legacy_jpy_and_cannot_erase_new_cny_original():
    reset_schema()
    key = str(uuid4())
    try:
        run_alembic(command.upgrade, _PARENT)
        seed_owner()
        with SessionLocal.begin() as db:
            activate_test_currency_authority(db, "JPY")
            db.execute(text("""INSERT INTO repayment_drafts (public_id, tenant_id, created_by_account_id,
                source, amount_cents, home_currency_code, captured_at, draft_idempotency_key, status, created_at)
                SELECT :key, 'owner', account_id, 'other', 1200, 'JPY', '2020-01-02T03:04:05Z', :key,
                    'pending', '2020-01-02T03:05:00Z' FROM ledger_members
                WHERE ledger_id = 'owner' AND role = 'owner' LIMIT 1"""), {"key": key})
        with engine.connect() as db:
            before = dict(db.execute(text("SELECT * FROM repayment_drafts WHERE public_id = :key"), {"key": key}).mappings().one())
        run_alembic(command.upgrade, _HEAD)
        with engine.connect() as db:
            after = dict(db.execute(text("SELECT * FROM repayment_drafts WHERE public_id = :key"), {"key": key}).mappings().one())
            assert {name: after[name] for name in before} == before
            assert after["original_currency_code"] is None and after["original_amount_minor"] is None
            import_module("migrations.versions.20260930_0001_repayment_capture_money").assert_postcondition(db)
        # A legacy-only downgrade loses no newly recorded originals.
        run_alembic(command.downgrade, _PARENT)
        run_alembic(command.upgrade, _HEAD)
        with SessionLocal.begin() as db:
            activate_test_currency_authority(db, "JPY")
            db.execute(text("UPDATE repayment_drafts SET original_currency_code = 'CNY', original_amount_minor = 50000, "
                "amount_cents = NULL WHERE public_id = :key"), {"key": key})
        with SessionLocal.begin() as db, pytest.raises(DBAPIError, match="ck_repayment_drafts_captured_money"):
            activate_test_currency_authority(db, "JPY")
            db.execute(text("UPDATE repayment_drafts SET original_currency_code = NULL WHERE public_id = :key"), {"key": key})
        with pytest.raises(RuntimeError, match="cannot erase captured original repayment money"):
            run_alembic(command.downgrade, _PARENT)
        with engine.connect() as db:
            assert db.scalar(text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1")) == _HEAD
            assert db.execute(text("SELECT amount_cents, home_currency_code, original_currency_code, original_amount_minor "
                "FROM repayment_drafts WHERE public_id = :key"), {"key": key}).one() == (None, "JPY", "CNY", 50000)
    finally:
        reset_schema()
