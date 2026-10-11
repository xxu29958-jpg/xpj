"""Legacy time preservation, date-only facts, and a lossless downgrade boundary."""

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
_PARENT = "20261008_0001"
_HEAD = "20261011_0001"
_TABLES = ("repayments", "member_repayment_proposals", "repayment_drafts")


def _rows():
    with engine.connect() as db:
        return {table: [dict(row) for row in db.execute(text(f"SELECT * FROM {table} ORDER BY id")).mappings()]
            for table in _TABLES}


def _seed_legacy():
    account, _ = seed_owner()
    with SessionLocal.begin() as db:
        activate_test_currency_authority(db, "CNY")
        debt = db.scalar(text("""INSERT INTO debts (public_id, tenant_id, owner_account_id,
            created_by_account_id, direction, counterparty_type, counterparty_label,
            principal_amount_cents, home_currency_code, status, source_type, created_at, updated_at)
            VALUES (:key, 'owner', :actor, :actor, 'i_owe', 'external', '原往来', 10000, 'CNY',
                'open', 'manual', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) RETURNING id"""),
            {"key": str(uuid4()), "actor": account})
        db.execute(text("""INSERT INTO repayments (public_id, debt_id, amount_cents, paid_at,
            actor_account_id, idempotency_key, created_at) VALUES (:key, :debt, 1000,
            '2020-01-02T03:04:05Z', :actor, :key, '2020-01-03T05:06:07Z')"""),
            {"key": str(uuid4()), "debt": debt, "actor": account})
        db.execute(text("""INSERT INTO member_repayment_proposals (public_id, debt_id, debtor_account_id,
            creditor_account_id, proposed_by_account_id, proposed_amount_cents, home_currency_code,
            paid_at, status, idempotency_key, created_at, expires_at) VALUES (:key, :debt, :actor,
            :actor, :actor, 500, 'CNY', '2020-01-02T03:04:05Z', 'pending', :key,
            '2020-01-03T05:06:07Z', '2020-01-10T00:00:00Z')"""),
            {"key": str(uuid4()), "debt": debt, "actor": account})
        db.execute(text("""INSERT INTO repayment_drafts (public_id, tenant_id, created_by_account_id,
            source, amount_cents, home_currency_code, captured_at, draft_idempotency_key, status, created_at)
            VALUES (:key, 'owner', :actor, 'other', 500, 'CNY', '2020-01-02T03:04:05Z', :key,
                'pending', '2020-01-03T05:06:07Z')"""), {"key": str(uuid4()), "actor": account})
    return account, debt


def test_migration_preserves_old_instants_and_refuses_erasing_new_date_only_evidence():
    reset_schema()
    try:
        run_alembic(command.upgrade, _PARENT)
        account, debt = _seed_legacy()
        before = _rows()
        run_alembic(command.upgrade, _HEAD)
        for table, rows in _rows().items():
            for old, new in zip(before[table], rows, strict=True):
                assert new.pop("accounting_time_snapshot") is None
                assert new == old
        with engine.connect() as db:
            import_module("migrations.versions.20261011_0001_repayment_accounting_time").assert_postcondition(db)
        run_alembic(command.downgrade, _PARENT)
        assert _rows() == before
        run_alembic(command.upgrade, _HEAD)
        snapshot = json.dumps({"precision": "date_only", "instant_utc": None,
            "user_local_date": "2026-04-30", "accounting_date": "2026-05-01", "calendar_revision": 3,
            "source_timezone": None, "source_utc_offset_seconds": None, "basis": "user_selected"})
        insert = text("""INSERT INTO repayments (public_id, debt_id, amount_cents, paid_at,
            accounting_time_snapshot, actor_account_id, idempotency_key, created_at)
            VALUES (:key, :debt, 500, :instant, CAST(:snapshot AS jsonb), :actor, :key, CURRENT_TIMESTAMP)""")
        values = {"key": str(uuid4()), "debt": debt, "actor": account, "snapshot": snapshot}
        with SessionLocal.begin() as db, pytest.raises(DBAPIError, match="ck_repayments_payment_time"):
            activate_test_currency_authority(db, "CNY")
            db.execute(insert, {**values, "instant": "2026-04-30T00:00:00Z"})
        with SessionLocal.begin() as db:
            activate_test_currency_authority(db, "CNY")
            db.execute(insert, {**values, "instant": None})
        saved = _rows()
        with pytest.raises(RuntimeError, match="cannot erase original repayment time evidence"):
            run_alembic(command.downgrade, _PARENT)
        assert _rows() == saved
        with engine.connect() as db:
            assert db.scalar(text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1")) == _HEAD
    finally:
        reset_schema()
