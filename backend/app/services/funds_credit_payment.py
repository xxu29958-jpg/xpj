"""Credit principal is settled in its native currency, with one actual payer debit."""
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import (
    AccountMovement,
    CreditFacility,
    Debt,
    Expense,
    ExpenseFunding,
    FinancialAccount,
    Repayment,
    RepaymentDraft,
)
from app.money_contract import ensure_money_minor
from app.schemas._accounting_time import AccountingTimeInput
from app.schemas.funds import CreditPayment, FinancialAccountReceipt
from app.services.credit_allocation_service import allocate_credit
from app.services.credit_fee_settlement import reviewed_fee_settlement
from app.services.debt_service._repayment_time import resolve_repayment_time
from app.services.funds_commands import claim_funds, finish_funds, movement, replay_funds, require_account_version
from app.services.funds_fact_service import validate_movement_date
from app.services.funds_money import valuation
from app.services.funds_query import account_balance, get_account
from app.services.funds_repayment_capture import prepare_repayment_capture, review_capture_amount
from app.services.installment_settlement import record_installment_payments, reviewed_settlement
from app.services.repayment_draft_resolution import resolve_repayment_draft, reverse_source_expense
from app.services.time_service import now_utc
from app.tenants import AuthContext


def pay_credit(db: Session, *, auth: AuthContext, public_id: str, payload: CreditPayment, key: str) -> FinancialAccountReceipt:
    claim = claim_funds(db, auth, payload, key, "pay_credit_from_account", public_id)
    if claim is None:
        return replay_funds(db, auth, key)
    draft = prepare_repayment_capture(db, auth, payload)
    credit, payer = _payment_accounts(db, auth, public_id, payload, draft)
    review_capture_amount(db, draft, credit, payer, payload)
    if draft is not None:
        reverse_source_expense(db, draft, auth.account_id)
    debt = db.scalar(select(Debt).join(CreditFacility, CreditFacility.debt_id == Debt.id)
        .where(CreditFacility.account_id == credit.id).with_for_update(of=Debt))
    if debt.debt_kind == "one_off" and payload.principal_minor > max(0, -account_balance(db, credit)):
        raise AppError("debt_amount_invalid", "固定本金贷款的本次清偿不能超过未偿本金。", status_code=422)
    fee_allocations, fee_amount = reviewed_fee_settlement(db, credit, payer, payload)
    allocations, periods = reviewed_settlement(db, credit, payer, payload)
    allocations.update(fee_allocations)
    credit_amount = ensure_money_minor(payload.principal_minor + fee_amount, sign="nonnegative", label="credit.total_payment")
    payer_amount = ensure_money_minor(payload.payer_amount_minor + payload.payer_fee_amount_minor, sign="nonnegative", label="credit.payer_payment")
    repayment, home_principal, snapshot = _repayment_fact(db, auth, credit, debt, payload, key)
    event = str(uuid4())
    fee = _payment_fee(db, auth, credit, payer, payload, key, event, repayment)
    credit_movement = None
    if credit_amount:
        home_principal, snapshot = valuation(db, ledger_id=credit.tenant_id, currency=credit.currency_code,
            amount_minor=credit_amount, occurred_on=payload.occurred_on, required=True)
        credit_movement = movement(db, auth, credit, event=event, component="credit", kind="repayment", amount=credit_amount,
            home_amount=home_principal, valuation_snapshot=snapshot, occurred_on=payload.occurred_on,
            note=payload.note, repayment_id=repayment.id,
            settlement_targets={str(identifier): amount for identifier, amount in allocations.items()})
        movement(db, auth, payer, event=event, component="payer", kind="repayment", amount=-payer_amount,
            occurred_on=payload.occurred_on, note=payload.note, repayment_id=repayment.id)
    db.flush()
    record_installment_payments(db, repayment, periods, fee)
    if credit_movement is not None:
        allocate_credit(db, credit)
    credit.row_version += 1
    payer.row_version += 1
    debt.row_version += 1
    db.flush()
    debt.status = "cleared" if account_balance(db, credit) >= 0 else "open"
    debt.updated_at = now_utc()
    if draft is not None:
        resolve_repayment_draft(db, draft, actor_account_id=auth.account_id,
            debt_public_id=debt.public_id, repayment_public_id=repayment.public_id)
    return finish_funds(db, auth, claim, credit)


def _payment_accounts(db: Session, auth: AuthContext, public_id: str, payload: CreditPayment,
                      draft: RepaymentDraft | None) -> tuple[FinancialAccount, FinancialAccount]:
    identifiers = {public_id, payload.payer_public_id}
    if draft is not None and draft.source_expense_public_id:
        identifiers.update(db.scalars(select(FinancialAccount.public_id)
            .join(ExpenseFunding, ExpenseFunding.account_id == FinancialAccount.id)
            .join(Expense, Expense.id == ExpenseFunding.expense_id).where(
                Expense.tenant_id == draft.tenant_id, ExpenseFunding.tenant_id == draft.tenant_id,
                ExpenseFunding.voided_at.is_(None),
                Expense.public_id == draft.source_expense_public_id)))
    accounts = {identifier: get_account(db, ledger_id=auth.tenant_id, actor_account_id=auth.account_id,
        public_id=identifier, lock=True) for identifier in sorted(identifiers)}
    credit, payer = accounts[public_id], accounts[payload.payer_public_id]
    require_account_version(credit, payload.expected_row_version)
    require_account_version(payer, payload.payer_row_version)
    validate_movement_date(db, credit, payload.occurred_on)
    validate_movement_date(db, payer, payload.occurred_on)
    if credit.kind != "credit" or payer.kind == "credit" or credit.id == payer.id:
        raise AppError("invalid_request", "请选择信用账户和实际扣款的现金、银行卡或余额账户。", status_code=422)
    if not credit.balance_known:
        raise AppError("credit_opening_unknown", "请先核对初始欠款，保留本次付款输入。", status_code=409)
    if credit.currency_code == payer.currency_code and payload.principal_minor != payload.payer_amount_minor:
        raise AppError("funding_amount_mismatch", "同币种本金清偿与实际付款必须一致；费用请单独记录。", status_code=422)
    return credit, payer


def _repayment_fact(db: Session, auth: AuthContext, credit: FinancialAccount, debt: Debt,
                    payload: CreditPayment, key: str) -> tuple[Repayment, int, dict]:
    home_principal, snapshot = valuation(db, ledger_id=credit.tenant_id, currency=credit.currency_code,
        amount_minor=payload.principal_minor, occurred_on=payload.occurred_on, required=True)
    payment_time = resolve_repayment_time(db, ledger_id=credit.tenant_id, paid_at=None,
        time_input=AccountingTimeInput(precision="date_only", user_local_date=payload.occurred_on,
            calendar_revision=payload.calendar_revision))
    repayment = Repayment(debt_id=debt.id, amount_cents=home_principal, settlement_kind="credit",
        original_currency_code=credit.currency_code, original_amount_minor=payload.principal_minor,
        exchange_rate_to_cny=Decimal(snapshot["rate"]) if snapshot["rate"] is not None else None, exchange_rate_source=snapshot["source"],
        exchange_rate_date=datetime.fromisoformat(snapshot["rate_date"]).replace(tzinfo=UTC),
        paid_at=None, accounting_time_snapshot=payment_time.model_dump(mode="json"),
        actor_account_id=auth.account_id, idempotency_key=key)
    db.add(repayment)
    db.flush()
    return repayment, home_principal, snapshot


def _payment_fee(db: Session, auth: AuthContext, credit: FinancialAccount, payer: FinancialAccount,
                 payload: CreditPayment, key: str, event: str, repayment: Repayment) -> Expense | None:
    fee = None
    if payload.new_fee_minor:
        from app.schemas import ExpenseManualCreateRequest
        from app.schemas.funds import FundingPart
        from app.services.expense_service._create import create_manual_expense
        from app.services.ledger_calendar_service import current_calendar
        if not payload.fee_note:
            raise AppError("invalid_request", "请填写这次新发生费用的依据；已记过的费用不要再次填写。", status_code=422)
        fee = create_manual_expense(db, ExpenseManualCreateRequest(client_ref=f"funds-fee:{key}",
            original_currency_code=payer.currency_code, original_amount_minor=payload.new_fee_minor,
            merchant=credit.name, category="其他", note=payload.fee_note,
            time_input=AccountingTimeInput(precision="date_only", user_local_date=payload.occurred_on,
                calendar_revision=current_calendar(db, ledger_id=auth.tenant_id).revision),
            funding=[FundingPart(component_id="fee", account_public_id=payer.public_id,
                account_row_version=payer.row_version, expense_amount_minor=payload.new_fee_minor,
                account_amount_minor=payload.new_fee_minor)]), auth, commit=False)
        fee_movement = db.scalar(select(AccountMovement).join(ExpenseFunding, ExpenseFunding.id == AccountMovement.funding_id)
            .where(ExpenseFunding.expense_id == fee.id))
        fee_movement.event_public_id, fee_movement.repayment_id = event, repayment.id
    return fee
