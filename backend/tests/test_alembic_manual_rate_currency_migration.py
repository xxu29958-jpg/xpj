"""Real PostgreSQL: retain the recorded pair without guessing unadopted history."""

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
_PARENT = "20260907_0001"
_HEAD = "20260908_0001"
_INSERT = """
    INSERT INTO exchange_rates (public_id, tenant_id, currency_code, rate_date,
        rate_to_cny, source, created_at, updated_at)
    VALUES (:id, 'owner', 'USD', '2026-09-08', 150, 'manual', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
"""


@pytest.mark.parametrize("home", ["CNY", "JPY"])
def test_manual_rates_acquire_the_persisted_currency_without_changing_the_rate(home, monkeypatch):
    reset_schema()
    try:
        run_alembic(command.upgrade, _PARENT)
        seed_owner()
        key = str(uuid4())
        with SessionLocal() as db:
            activate_test_currency_authority(db, home)
            db.execute(text(_INSERT), {"id": key})
            db.commit()
        monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "EUR")
        run_alembic(command.upgrade, _HEAD)
        with engine.connect() as db:
            row = db.execute(text("SELECT public_id, currency_code, home_currency_code, rate_to_cny FROM exchange_rates")).one()
            assert tuple(row) == (key, "USD", home, 150)
        with SessionLocal() as db, pytest.raises(DBAPIError, match="currency pair is immutable"):
            resolve_write_capability(db)
            db.execute(text("UPDATE exchange_rates SET home_currency_code = 'EUR' WHERE public_id = :id"), {"id": key})
        with SessionLocal() as db, pytest.raises(DBAPIError, match="requires target currency"):
            resolve_write_capability(db)
            db.execute(text(_INSERT), {"id": str(uuid4())})
        with pytest.raises(RuntimeError, match="cannot erase persisted manual rate currencies"):
            run_alembic(command.downgrade, _PARENT)
        with engine.connect() as db:
            assert db.scalar(text("SELECT home_currency_code FROM exchange_rates WHERE public_id = :id"), {"id": key}) == home
    finally:
        reset_schema()


def test_unadopted_manual_rate_waits_for_the_same_audited_owner_transaction():
    reset_schema()
    try:
        run_alembic(command.upgrade, "20260729_0001")
        with SessionLocal() as db:
            bootstrap = bootstrap_owner(db, account_name="Owner", ledger_name="Owner ledger", device_name="migration-admin")
            key = str(uuid4())
            db.execute(text(_INSERT), {"id": key})
            db.commit()
        run_alembic(command.upgrade, _HEAD)
        with SessionLocal() as db:
            assert db.scalar(text("SELECT home_currency_code FROM exchange_rates")) is None
            auth = authenticate_session_token(db, bootstrap.admin_token, {"app", "admin"})
            preview = adoption_preview(db)
            assert "JPY" in preview.allowed_home_currency_codes
            receipt = adopt_currency_binding(
                db, auth=auth, idempotency_key=uuid4(), home_code="JPY",
                expected_contract_version=preview.currency_contract_version,
                expected_state=preview.state, expected_revision=preview.binding_revision,
                expected_evidence_sha256=preview.evidence_sha256, reason="Owner verified the historical USD to JPY rate.",
            )
            assert receipt.home_currency_code == "JPY"
            row = db.execute(text("SELECT public_id, currency_code, home_currency_code, rate_to_cny FROM exchange_rates")).one()
            assert tuple(row) == (key, "USD", "JPY", 150)
    finally:
        reset_schema()
