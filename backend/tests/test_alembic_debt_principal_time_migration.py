"""Add occurrence evidence without guessing old dates or permitting lossy rollback."""

import json
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
_PARENT = "20261011_0001"
_HEAD = "20261012_0001"


def _rows():
    with engine.connect() as db:
        return [dict(row) for row in db.execute(text("SELECT * FROM debts ORDER BY id")).mappings()]


def test_principal_migration_preserves_old_rows_and_refuses_erasing_new_evidence():
    reset_schema()
    try:
        run_alembic(command.upgrade, _PARENT)
        actor, _ = seed_owner()
        with SessionLocal.begin() as db:
            activate_test_currency_authority(db, "CNY")
            db.execute(text("""INSERT INTO debts (public_id, tenant_id, owner_account_id, created_by_account_id,
                direction, counterparty_type, counterparty_label, principal_amount_cents, home_currency_code,
                source_type, created_at, updated_at) VALUES (:key, 'owner', :actor, :actor, 'i_owe', 'external',
                '旧本金', 10000, 'CNY', 'manual', '2020-01-02T03:04:05Z', '2020-01-02T03:04:05Z')"""),
                {"key": str(uuid4()), "actor": actor})
        before = _rows()
        run_alembic(command.upgrade, _HEAD)
        after = _rows()
        assert after[0].pop("accounting_time_snapshot") is None
        assert after == before
        with engine.connect() as db:
            import_module("migrations.versions.20261012_0001_debt_principal_time").assert_postcondition(db)
        run_alembic(command.downgrade, _PARENT)
        assert _rows() == before
        run_alembic(command.upgrade, _HEAD)
        snapshot = {"precision": "date_only", "instant_utc": None, "user_local_date": "2026-01-31",
            "accounting_date": "2026-01-31", "calendar_revision": 3, "basis": "user_date"}
        update = text("UPDATE debts SET accounting_time_snapshot = CAST(:snapshot AS jsonb)")
        with SessionLocal.begin() as db, pytest.raises(DBAPIError, match="ck_debts_principal_time"):
            activate_test_currency_authority(db, "CNY")
            db.execute(update, {"snapshot": json.dumps({**snapshot, "instant_utc": "2026-01-31T00:00:00Z"})})
        with SessionLocal.begin() as db:
            activate_test_currency_authority(db, "CNY")
            db.execute(update, {"snapshot": json.dumps(snapshot)})
        saved = _rows()
        with pytest.raises(RuntimeError, match="cannot erase original principal time evidence"):
            run_alembic(command.downgrade, _PARENT)
        assert _rows() == saved
        with engine.connect() as db:
            assert db.scalar(text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1")) == _HEAD
    finally:
        reset_schema()
