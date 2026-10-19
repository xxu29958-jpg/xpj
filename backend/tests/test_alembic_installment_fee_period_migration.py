"""Actual fee-only history remains readable across the schema boundary."""
from datetime import date
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.database import SessionLocal, engine
from app.models import (
    AccountMovement,
    CreditApplicationReview,
    CreditFeeObligation,
    Expense,
    FinancialAccount,
    InstallmentAgreement,
    InstallmentPeriod,
)
from tests._infra.c07_money_migration import reset_schema, run_alembic, seed_owner
from tests._infra.currency import activate_test_currency_authority

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]


def test_fee_only_period_survives_upgrade_and_refuses_lossy_downgrade():
    parent, head = "20261019_0001", "20261019_0005"
    reset_schema()
    try:
        run_alembic(command.upgrade, head)
        run_alembic(command.downgrade, "20261019_0003")
        run_alembic(command.upgrade, head)
        run_alembic(command.downgrade, "20261019_0002")
        run_alembic(command.upgrade, head)
        run_alembic(command.downgrade, parent)
        actor, _ = seed_owner()
        run_alembic(command.upgrade, head)
        with SessionLocal.begin() as db:
            activate_test_currency_authority(db, "KWD")
            account = FinancialAccount(tenant_id="owner", owner_account_id=actor, name="已还本金的分期",
                kind="credit", currency_code="KWD", visibility="private", balance_known=True,
                opening_date=date.today(), opening_source="外部账单核对")
            db.add(account)
            db.flush()
            agreement = InstallmentAgreement(account_id=account.id, series_id=str(uuid4()), revision=1,
                name="仅余费用", source="真实合约修订", agreed_on=date.today(), actor_account_id=actor)
            db.add(agreement)
            db.flush()
            period = InstallmentPeriod(agreement_id=agreement.id, position=1, due_on=date.today(), principal_minor=0, planned_fee_minor=12345)
            expense = Expense(tenant_id="owner", home_currency_code="KWD", original_currency_code="KWD",
                original_amount_minor=12345, amount_cents=12345, merchant="已发生费用", status="confirmed", source="手动记账")
            db.add_all([period, expense])
            db.flush()
            db.add(CreditFeeObligation(expense_id=expense.id, account_id=account.id, period_id=period.id))
            _seed_review(db, account, actor)
        for value in (-1, 0):
            with SessionLocal.begin() as db, pytest.raises(DBAPIError):
                db.execute(text("UPDATE installment_periods SET planned_fee_minor=:value"), {"value": value})
        with SessionLocal.begin() as db, pytest.raises(DBAPIError):
            db.execute(text("UPDATE credit_application_reviews SET reason='rewrite history'"))
        with pytest.raises(RuntimeError, match="downgrade refused"):
            run_alembic(command.downgrade, parent)
        with engine.connect() as db:
            assert db.scalar(text("SELECT schema_revision FROM dataset_authority WHERE singleton_id=1")) == head
            assert db.execute(text("SELECT principal_minor, planned_fee_minor FROM installment_periods")).one() == (0, 12345)
    finally:
        reset_schema()


def _seed_review(db, account, actor):
    facts = [AccountMovement(tenant_id="owner", account_id=account.id, event_public_id=str(uuid4()),
        component_id="opening", kind="opening", amount_minor=amount, home_amount_cents=amount,
        home_currency_code="KWD", occurred_on=date.today(), note="本人核对", actor_account_id=actor)
        for amount in (12345, -12345)]
    db.add_all(facts)
    db.flush()
    db.add(CreditApplicationReview(account_id=account.id, credit_movement_id=facts[0].id,
        draw_movement_id=facts[1].id, amount_minor=12345, reason="明确抵扣", actor_account_id=actor))
