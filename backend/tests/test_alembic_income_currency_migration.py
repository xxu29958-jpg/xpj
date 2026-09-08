"""Income currency migration retains amounts, revision identity and immutability."""

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
_PARENT = "20260908_0002"
_HEAD = "20260908_0003"
_INSERT_PLAN = """
    INSERT INTO monthly_income_plans (public_id, tenant_id, label, source_type, frequency,
        income_month, amount_cents, pay_day, status, row_version, created_at, updated_at)
    VALUES (:key, 'owner', 'Salary', 'salary', 'monthly', NULL, 1200, 10, 'active', 1,
        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) RETURNING id
"""


def _seed_plan(db):
    key = str(uuid4())
    plan_id = db.scalar(text(_INSERT_PLAN), {"key": key})
    db.commit()
    return key, plan_id


@pytest.mark.parametrize("home", ["CNY", "JPY"])
def test_income_plan_and_immutable_history_acquire_only_the_persisted_currency(home, monkeypatch):
    reset_schema()
    try:
        run_alembic(command.upgrade, _PARENT)
        seed_owner()
        with SessionLocal() as db:
            activate_test_currency_authority(db, home)
            key, plan_id = _seed_plan(db)
            revision_id = db.scalar(text("""
                INSERT INTO income_plan_revisions (tenant_id, plan_id, revision_number, effective_month,
                    intent_month, change_kind, label, source_type, frequency, amount_cents, pay_day, status, recorded_at)
                VALUES ('owner', :plan, 1, '2026-09-01', '2026-09-01', 'create', 'Salary', 'salary',
                    'monthly', 1200, 10, 'active', CURRENT_TIMESTAMP) RETURNING id
            """), {"plan": plan_id})
            db.commit()
        monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "EUR")
        run_alembic(command.upgrade, _HEAD)
        with engine.connect() as db:
            assert tuple(db.execute(text("SELECT id, public_id, home_currency_code, amount_cents, row_version FROM monthly_income_plans")).one()) == (plan_id, key, home, 1200, 1)
            assert tuple(db.execute(text("SELECT id, plan_id, home_currency_code, amount_cents, revision_number FROM income_plan_revisions")).one()) == (revision_id, plan_id, home, 1200, 1)
        with SessionLocal() as db, pytest.raises(DBAPIError, match="income plan revisions are immutable"):
            resolve_write_capability(db)
            db.execute(text("UPDATE income_plan_revisions SET home_currency_code = 'EUR' WHERE id = :id"), {"id": revision_id})
        with SessionLocal() as db, pytest.raises(DBAPIError, match="income requires its captured currency"):
            resolve_write_capability(db)
            db.execute(text(_INSERT_PLAN), {"key": str(uuid4())})
        with pytest.raises(RuntimeError, match="cannot erase recorded income currencies"):
            run_alembic(command.downgrade, _PARENT)
    finally:
        reset_schema()


def test_unknown_income_history_is_declared_in_the_same_owner_adoption_transaction():
    reset_schema()
    try:
        run_alembic(command.upgrade, "20260729_0001")
        with SessionLocal() as db:
            bootstrap = bootstrap_owner(db, account_name="Owner", ledger_name="Owner ledger", device_name="migration-admin")
            key, _ = _seed_plan(db)
        run_alembic(command.upgrade, _HEAD)
        with engine.connect() as db:
            assert db.scalar(text("SELECT home_currency_code FROM monthly_income_plans")) is None
            assert db.scalar(text("SELECT home_currency_code FROM income_plan_revisions")) is None
        with SessionLocal() as db:
            auth = authenticate_session_token(db, bootstrap.admin_token, {"app", "admin"})
            preview = adoption_preview(db)
            receipt = adopt_currency_binding(
                db, auth=auth, idempotency_key=uuid4(), home_code="CNY",
                expected_contract_version=preview.currency_contract_version,
                expected_state=preview.state, expected_revision=preview.binding_revision,
                expected_evidence_sha256=preview.evidence_sha256, reason="Owner verified the historical income as CNY.",
            )
            assert receipt.home_currency_code == "CNY"
            assert tuple(db.execute(text("SELECT public_id, home_currency_code, amount_cents FROM monthly_income_plans")).one()) == (key, "CNY", 1200)
            assert tuple(db.execute(text("SELECT home_currency_code, amount_cents, change_kind FROM income_plan_revisions")).one()) == ("CNY", 1200, "baseline")
        with SessionLocal() as db, pytest.raises(DBAPIError, match="income plan revisions are immutable"):
            resolve_write_capability(db)
            db.execute(text("UPDATE income_plan_revisions SET amount_cents = 1"))
    finally:
        reset_schema()
