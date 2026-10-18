"""Undo a recorded principal payment with its actual account and allocation facts."""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import AccountMovement, CreditFacility, Debt, FinancialAccount, Repayment, RepaymentVoid
from app.schemas.funds import CreditPaymentVoid, FinancialAccountView
from app.services.funds_commands import claim_funds, finish_funds, replay_funds, require_account_version
from app.services.funds_fact_service import reverse_movements, validate_movement_date
from app.services.funds_query import get_account
from app.tenants import AuthContext


def void_credit_payment(db: Session, *, auth: AuthContext, public_id: str,
        payload: CreditPaymentVoid, key: str) -> FinancialAccountView:
    claim = claim_funds(db, auth, payload, key, "void_credit_payment", public_id)
    if claim is None:
        return replay_funds(db, auth, key)
    account = get_account(db, ledger_id=auth.tenant_id, actor_account_id=auth.account_id, public_id=public_id)
    repayment = db.scalar(select(Repayment).join(CreditFacility, CreditFacility.debt_id == Repayment.debt_id)
        .where(CreditFacility.account_id == account.id, Repayment.public_id == payload.repayment_public_id))
    if repayment is None:
        raise AppError("repayment_not_found", status_code=404)
    # Fees have their own Expense and correction/refund entry. They are not principal.
    rows = list(db.scalars(select(AccountMovement).where(AccountMovement.repayment_id == repayment.id,
        AccountMovement.kind == "repayment", AccountMovement.reversal_of_id.is_(None))))
    if not rows:
        raise AppError("invalid_request", "请从原还款记录办理更正。", status_code=422)
    identifiers = db.scalars(select(FinancialAccount.public_id).where(
        FinancialAccount.id.in_({row.account_id for row in rows})).order_by(FinancialAccount.public_id)).all()
    accounts = [get_account(db, ledger_id=auth.tenant_id, actor_account_id=auth.account_id,
        public_id=identifier, lock=True) for identifier in identifiers]
    require_account_version(account, payload.expected_row_version, allow_archived=True)
    for row in accounts:
        validate_movement_date(db, row, payload.occurred_on)
    if payload.occurred_on < max(row.occurred_on for row in rows):
        raise AppError("invalid_request", "更正日期不能早于原还款日期。", status_code=422)
    db.scalar(select(Debt).where(Debt.id == repayment.debt_id).with_for_update())
    void_credit_payment_facts(db, ledger_id=auth.tenant_id, actor_account_id=auth.account_id,
        repayment=repayment, rows=rows, reason=payload.reason, occurred_on=payload.occurred_on, key=key)
    return finish_funds(db, auth, claim, account)


def void_credit_payment_facts(db: Session, *, ledger_id: str, actor_account_id: int,
        repayment: Repayment, rows: list[AccountMovement], reason: str, occurred_on: date, key: str) -> None:
    if db.scalar(select(RepaymentVoid.id).where(RepaymentVoid.repayment_id == repayment.id)) is not None:
        raise AppError("repayment_already_voided", "这笔还款已撤销，请查看原记录。", status_code=409)
    db.add(RepaymentVoid(repayment_id=repayment.id, actor_account_id=actor_account_id,
        reason=reason, idempotency_key=key))
    reverse_movements(db, ledger_id=ledger_id, actor_account_id=actor_account_id, rows=rows,
        reason=reason, occurred_on=occurred_on)
    if not rows:
        debt = db.scalar(select(Debt).where(Debt.id == repayment.debt_id).with_for_update())
        debt.row_version += 1
        db.flush()
