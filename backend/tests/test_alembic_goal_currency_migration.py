"""A spending target gains proven units while debt-clearance goals stay nonmonetary."""

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
_PARENT = "20260909_0001"
_INSERT = """
    INSERT INTO goals (public_id, tenant_id, name, goal_type, period, month,
        target_amount_cents, status, row_version, created_at, updated_at)
    VALUES (:key, 'owner', 'Transport limit', 'spending_limit', 'monthly', '2026-09',
        1200, 'active', 7, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
"""


def _seed_target(db):
    key = str(uuid4())
    db.execute(text(_INSERT), {"key": key})
    db.commit()
    return key


@pytest.mark.parametrize("home", ["CNY", "JPY"])
def test_goal_upgrade_keeps_amounts_versions_and_debt_goal_shape(home, monkeypatch):
    reset_schema()
    try:
        run_alembic(command.upgrade, _PARENT)
        seed_owner()
        with SessionLocal() as db:
            activate_test_currency_authority(db, home)
            key = _seed_target(db)
            resolve_write_capability(db)
            db.execute(text("""INSERT INTO goals (public_id, tenant_id, name, goal_type, period,
                status, row_version, goal_version, created_at, updated_at)
                VALUES ('debt-goal', 'owner', 'Clear debts', 'debt_repayment', 'monthly',
                    'active', 9, 4, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""))
            db.commit()
        monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "EUR")
        run_alembic(command.upgrade, "head")
        with engine.connect() as db:
            assert tuple(db.execute(text("SELECT public_id, home_currency_code, target_amount_cents, row_version "
                "FROM goals WHERE goal_type = 'spending_limit'")).one()) == (key, home, 1200, 7)
            assert tuple(db.execute(text("SELECT home_currency_code, target_amount_cents, row_version, goal_version "
                "FROM goals WHERE goal_type = 'debt_repayment'")).one()) == (None, None, 9, 4)
        with SessionLocal() as db, pytest.raises(DBAPIError, match="goal currency cannot relabel"):
            resolve_write_capability(db)
            db.execute(text("UPDATE goals SET home_currency_code = 'EUR' WHERE goal_type = 'spending_limit'"))
        with SessionLocal() as db, pytest.raises(DBAPIError, match="goal requires its captured currency"):
            resolve_write_capability(db)
            db.execute(text(_INSERT), {"key": str(uuid4())})
        with pytest.raises(RuntimeError, match="cannot erase recorded goal currencies"):
            run_alembic(command.downgrade, _PARENT)
    finally:
        reset_schema()


def test_unknown_goal_currency_waits_for_owner_adoption():
    reset_schema()
    try:
        run_alembic(command.upgrade, "20260729_0001")
        with SessionLocal() as db:
            bootstrap = bootstrap_owner(db, account_name="Owner", ledger_name="Owner ledger", device_name="migration-admin")
            key = _seed_target(db)
        run_alembic(command.upgrade, "head")
        with engine.connect() as db:
            assert db.scalar(text("SELECT home_currency_code FROM goals")) is None
        with SessionLocal() as db:
            auth = authenticate_session_token(db, bootstrap.admin_token, {"app", "admin"})
            preview = adoption_preview(db)
            adopt_currency_binding(db, auth=auth, idempotency_key=uuid4(), home_code="CNY",
                expected_contract_version=preview.currency_contract_version, expected_state=preview.state,
                expected_revision=preview.binding_revision, expected_evidence_sha256=preview.evidence_sha256,
                reason="Owner verified the historical spending target as CNY.")
            assert tuple(db.execute(text("SELECT public_id, home_currency_code, target_amount_cents, row_version "
                "FROM goals")).one()) == (key, "CNY", 1200, 7)
    finally:
        reset_schema()
