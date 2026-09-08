"""Upgrade preserves budget amounts, versions and category parent identity."""

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
_PARENT = "20260908_0003"
_HEAD = "20260908_0004"
_INSERT = """
    INSERT INTO budgets (public_id, tenant_id, month, total_amount_cents,
        non_monthly_amount_cents, rollover_amount_cents, excluded_categories, row_version, created_at, updated_at)
    VALUES (:key, 'owner', '2026-09', 1200, 10, -20, '[]', 3, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
"""


def _seed_budget(db):
    key = str(uuid4())
    db.execute(text(_INSERT), {"key": key})
    db.execute(text("""
        INSERT INTO budget_categories (public_id, tenant_id, month, category, amount_cents, created_at, updated_at)
        VALUES (:key, 'owner', '2026-09', 'Food', 100, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """), {"key": str(uuid4())})
    db.commit()
    return key


@pytest.mark.parametrize("home", ["CNY", "JPY"])
def test_budget_upgrade_uses_persisted_currency_and_keeps_category_parent(home, monkeypatch):
    reset_schema()
    try:
        run_alembic(command.upgrade, _PARENT)
        seed_owner()
        with SessionLocal() as db:
            activate_test_currency_authority(db, home)
            key = _seed_budget(db)
        monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "EUR")
        run_alembic(command.upgrade, _HEAD)
        with engine.connect() as db:
            assert tuple(db.execute(text("SELECT public_id, home_currency_code, total_amount_cents, "
                "non_monthly_amount_cents, rollover_amount_cents, row_version FROM budgets")).one()) == (key, home, 1200, 10, -20, 3)
            assert tuple(db.execute(text("SELECT b.public_id, b.home_currency_code, c.amount_cents FROM budget_categories c "
                "JOIN budgets b ON b.tenant_id = c.tenant_id AND b.month = c.month")).one()) == (key, home, 100)
        with SessionLocal() as db, pytest.raises(DBAPIError, match="budget currency cannot relabel"):
            resolve_write_capability(db)
            db.execute(text("UPDATE budgets SET home_currency_code = 'EUR'"))
        with SessionLocal() as db, pytest.raises(DBAPIError, match="budget requires its captured currency"):
            resolve_write_capability(db)
            db.execute(text(_INSERT.replace("2026-09", "2026-10")), {"key": str(uuid4())})
        with pytest.raises(RuntimeError, match="cannot erase recorded budget currencies"):
            run_alembic(command.downgrade, _PARENT)
    finally:
        reset_schema()


def test_unknown_budget_currency_is_filled_only_by_owner_adoption():
    reset_schema()
    try:
        run_alembic(command.upgrade, "20260729_0001")
        with SessionLocal() as db:
            bootstrap = bootstrap_owner(db, account_name="Owner", ledger_name="Owner ledger", device_name="migration-admin")
            key = _seed_budget(db)
        run_alembic(command.upgrade, _HEAD)
        with engine.connect() as db:
            assert db.scalar(text("SELECT home_currency_code FROM budgets")) is None
        with SessionLocal() as db:
            auth = authenticate_session_token(db, bootstrap.admin_token, {"app", "admin"})
            preview = adoption_preview(db)
            receipt = adopt_currency_binding(db, auth=auth, idempotency_key=uuid4(), home_code="CNY",
                expected_contract_version=preview.currency_contract_version, expected_state=preview.state,
                expected_revision=preview.binding_revision, expected_evidence_sha256=preview.evidence_sha256,
                reason="Owner verified the historical budget as CNY.")
            assert receipt.home_currency_code == "CNY"
            assert tuple(db.execute(text("SELECT public_id, home_currency_code, total_amount_cents, row_version FROM budgets")).one()) == (key, "CNY", 1200, 3)
    finally:
        reset_schema()
