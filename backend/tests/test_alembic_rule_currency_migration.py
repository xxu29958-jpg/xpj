"""Persisted binding supplies legacy threshold units; runtime defaults never do."""

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
_PARENT = "20260909_0002"
_INSERT = """
    INSERT INTO category_rules (tenant_id, keyword, category, enabled, priority,
        amount_min_cents, row_version, created_at, updated_at)
    VALUES ('owner', :keyword, '购物', true, 1, 1200, 7, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
"""


def _seed_rule(db):
    key = str(uuid4())
    db.execute(text(_INSERT), {"keyword": key})
    db.commit()
    return key


@pytest.mark.parametrize("home", ["CNY", "JPY"])
def test_rule_upgrade_preserves_amount_version_and_nonmonetary_shape(home, monkeypatch):
    reset_schema()
    try:
        run_alembic(command.upgrade, _PARENT)
        seed_owner()
        with SessionLocal() as db:
            activate_test_currency_authority(db, home)
            key = _seed_rule(db)
            resolve_write_capability(db)
            db.execute(text("""INSERT INTO category_rules (tenant_id, keyword, category, enabled, priority,
                row_version, created_at, updated_at) VALUES ('owner', 'nonmoney', '购物', true, 2, 9,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""))
            db.commit()
        monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "EUR")
        run_alembic(command.upgrade, "head")
        with engine.connect() as db:
            assert tuple(db.execute(text("SELECT home_currency_code, amount_min_cents, row_version "
                "FROM category_rules WHERE keyword = :key"), {"key": key}).one()) == (home, 1200, 7)
            assert tuple(db.execute(text("SELECT home_currency_code, amount_min_cents, row_version "
                "FROM category_rules WHERE keyword = 'nonmoney'")).one()) == (None, None, 9)
        with SessionLocal() as db, pytest.raises(DBAPIError, match="rule currency cannot relabel"):
            resolve_write_capability(db)
            db.execute(text("UPDATE category_rules SET home_currency_code = 'EUR' WHERE keyword = :key"), {"key": key})
        with SessionLocal() as db, pytest.raises(DBAPIError, match="monetary rule requires its captured currency"):
            resolve_write_capability(db)
            db.execute(text(_INSERT), {"keyword": str(uuid4())})
        with pytest.raises(RuntimeError, match="cannot erase recorded rule currencies"):
            run_alembic(command.downgrade, _PARENT)
    finally:
        reset_schema()


def test_unknown_rule_currency_waits_for_owner_adoption():
    reset_schema()
    try:
        run_alembic(command.upgrade, "20260729_0001")
        with SessionLocal() as db:
            bootstrap = bootstrap_owner(db, account_name="Owner", ledger_name="Owner ledger", device_name="migration-admin")
            key = _seed_rule(db)
        run_alembic(command.upgrade, "head")
        with engine.connect() as db:
            assert db.scalar(text("SELECT home_currency_code FROM category_rules WHERE keyword = :key"), {"key": key}) is None
        with SessionLocal() as db:
            auth = authenticate_session_token(db, bootstrap.admin_token, {"app", "admin"})
            preview = adoption_preview(db)
            adopt_currency_binding(db, auth=auth, idempotency_key=uuid4(), home_code="CNY",
                expected_contract_version=preview.currency_contract_version, expected_state=preview.state,
                expected_revision=preview.binding_revision, expected_evidence_sha256=preview.evidence_sha256,
                reason="Owner verified the historical rule thresholds as CNY.")
            assert tuple(db.execute(text("SELECT home_currency_code, amount_min_cents, row_version "
                "FROM category_rules WHERE keyword = :key"), {"key": key}).one()) == ("CNY", 1200, 7)
    finally:
        reset_schema()
