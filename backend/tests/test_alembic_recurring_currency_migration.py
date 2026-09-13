"""Fixed-expense currency comes from persisted evidence, without changing money."""

from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.database import SessionLocal, engine
from app.services.currency_adoption_service import adopt_currency_binding, adoption_preview
from app.services.currency_binding_service import resolve_write_capability
from app.services.identity_service import authenticate_session_token, bootstrap_owner
from tests._infra.c07_money_migration import reset_schema, run_alembic, seed_owner
from tests._infra.currency import activate_test_currency_authority

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]
_PARENT = "20260908_0004"
_INSERT = """
    INSERT INTO recurring_items (public_id, tenant_id, merchant_key, merchant_name,
        frequency, baseline_amount_cents, last_amount_cents, occurrence_count,
        status, source, row_version, created_at, updated_at)
    VALUES (:key, 'owner', :key, 'Subscription', 'monthly', 1200, 1300, 3,
        'active', 'candidate', 4, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
"""


def _seed_recurring(db):
    key = str(uuid4())
    db.execute(text(_INSERT), {"key": key})
    db.commit()
    return key


@pytest.mark.parametrize("home", ["CNY", "JPY"])
def test_recurring_upgrade_preserves_amounts_versions_and_persisted_currency(home, monkeypatch):
    reset_schema()
    try:
        run_alembic(command.upgrade, _PARENT)
        seed_owner()
        with SessionLocal() as db:
            activate_test_currency_authority(db, home)
            key = _seed_recurring(db)
        monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "EUR")
        run_alembic(command.upgrade, "head")
        with engine.connect() as db:
            assert tuple(db.execute(text("SELECT public_id, home_currency_code, baseline_amount_cents, "
                "last_amount_cents, occurrence_count, row_version FROM recurring_items")).one()) == (key, home, 1200, 1300, 3, 4)
        with SessionLocal() as db, pytest.raises(DBAPIError, match="recurring currency cannot relabel"):
            resolve_write_capability(db)
            db.execute(text("UPDATE recurring_items SET home_currency_code = 'EUR'"))
        with SessionLocal() as db, pytest.raises(DBAPIError, match="recurring requires its captured currency"):
            resolve_write_capability(db)
            db.execute(text(_INSERT), {"key": str(uuid4())})
        with pytest.raises(RuntimeError, match="cannot erase recorded recurring currencies"):
            run_alembic(command.downgrade, _PARENT)
    finally:
        reset_schema()


def test_unknown_recurring_currency_waits_for_owner_adoption():
    reset_schema()
    try:
        run_alembic(command.upgrade, "20260729_0001")
        with SessionLocal() as db:
            bootstrap = bootstrap_owner(db, account_name="Owner", ledger_name="Owner ledger", device_name="migration-admin")
            key = _seed_recurring(db)
        run_alembic(command.upgrade, "head")
        with engine.connect() as db:
            assert db.scalar(text("SELECT home_currency_code FROM recurring_items")) is None
        with SessionLocal() as db:
            auth = authenticate_session_token(db, bootstrap.admin_token, {"app", "admin"})
            preview = adoption_preview(db)
            receipt = adopt_currency_binding(db, auth=auth, idempotency_key=uuid4(), home_code="CNY",
                expected_contract_version=preview.currency_contract_version, expected_state=preview.state,
                expected_revision=preview.binding_revision, expected_evidence_sha256=preview.evidence_sha256,
                reason="Owner verified the historical fixed expense as CNY.")
            assert receipt.home_currency_code == "CNY"
            assert tuple(db.execute(text("SELECT public_id, home_currency_code, baseline_amount_cents, "
                "last_amount_cents, occurrence_count, row_version FROM recurring_items")).one()) == (key, "CNY", 1200, 1300, 3, 4)
    finally:
        reset_schema()
