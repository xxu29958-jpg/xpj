"""Publish reviewed funding in the same transaction as its one Expense."""
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import (
    AccountMovement,
    CreditFacility,
    CreditFeeObligation,
    Debt,
    Expense,
    ExpenseFunding,
    ExpenseOffsetFact,
    FinancialAccount,
)
from app.money_contract import round_minor_ratio_half_up
from app.schemas.funds import FundingPart
from app.services.credit_allocation_service import allocate_credit
from app.services.funds_commands import movement
from app.services.funds_fact_service import (
    lock_reviewed_accounts,
    refresh_credit_debt,
    reverse_movements,
    unreversed_movements,
    validate_movement_date,
)
from app.services.time_service import now_utc


def validate_funding_currency(part, account, currency):
    if part.expense_currency_code not in (None, currency) or part.account_currency_code not in (None, account.currency_code):
        raise AppError("state_conflict", "原付款币种已变化，请保留金额并重新核对，不能直接重试。", status_code=409)
    if account.currency_code == currency and part.expense_amount_minor != part.account_amount_minor:
        raise AppError("funding_amount_mismatch", "同币种付款金额应与消费组成一致。", status_code=422)


def publish_expense_funding(db: Session, *, expense: Expense, parts: list[FundingPart], actor_account_id: int | None) -> None:
    if not parts:
        return
    total = _review_unfunded_expense(db, expense, parts, actor_account_id)
    accounts, debts = _review_funding_accounts(db, expense, parts, actor_account_id)
    event, allocated_home = str(uuid4()), 0
    for index, part in enumerate(parts):
        row = accounts[part.account_public_id]
        currency = expense.original_currency_code or expense.home_currency_code
        home = expense.amount_cents - allocated_home if index == len(parts) - 1 else round_minor_ratio_half_up(
            expense.amount_cents * part.expense_amount_minor, total, label="funding.home_allocation")
        allocated_home += home
        funding = ExpenseFunding(tenant_id=expense.tenant_id, expense_id=expense.id, account_id=row.id,
            component_id=part.component_id, expense_amount_minor=part.expense_amount_minor,
            account_amount_minor=part.account_amount_minor, expense_row_version=expense.row_version,
            actor_account_id=actor_account_id, included_in_opening=part.included_in_opening)
        db.add(funding)
        db.flush()
        if part.included_in_opening:
            continue
        movement(db, SimpleNamespace(account_id=actor_account_id), row, event=event, component=part.component_id,
            kind="credit_draw" if row.kind == "credit" else "expense", amount=-part.account_amount_minor,
            home_amount=-home, occurred_on=expense.accounting_date,
            valuation_snapshot={"kind": "expense_basis", "expense_public_id": expense.public_id,
                "expense_row_version": expense.row_version, "currency_code": currency,
                "home_currency_code": expense.home_currency_code,
                "rate": str(expense.exchange_rate_to_cny) if expense.exchange_rate_to_cny is not None else None,
                "rate_date": str(expense.exchange_rate_date), "source": expense.exchange_rate_source}
                if row.currency_code == currency else None,
            note=expense.merchant or "消费付款", funding_id=funding.id)
    for row in accounts.values():
        row.row_version += 1
        debt = debts.get(row.id)
        if debt is not None:
            allocate_credit(db, row)
            refresh_credit_debt(db, row, debt)
    db.flush()


def _review_unfunded_expense(db: Session, expense: Expense, parts: list[FundingPart], actor_account_id: int | None) -> int:
    if actor_account_id is None or expense.status != "confirmed" or expense.amount_cents is None:
        raise AppError("funding_requires_confirmation", "付款组成已保留；请先补齐金额和汇率，再一起确认。", status_code=409)
    if db.scalar(select(ExpenseOffsetFact.id).where(ExpenseOffsetFact.expense_id == expense.id,
            ExpenseOffsetFact.kind == "reversal", ExpenseOffsetFact.status == "active").limit(1)):
        raise AppError("expense_reversal_active", "原消费已冲销，不能再扣款；请从冲销记录核对。", status_code=409)
    if db.scalar(select(ExpenseFunding.id).where(ExpenseFunding.tenant_id == expense.tenant_id,
            ExpenseFunding.expense_id == expense.id, ExpenseFunding.voided_at.is_(None)).limit(1)) is not None:
        raise AppError("funding_already_recorded", "这笔消费已有付款组成，请从来源记录更正，不能再次扣款。", status_code=409)
    total = expense.original_amount_minor or expense.amount_cents
    if sum(part.expense_amount_minor for part in parts) != total or len({part.component_id for part in parts}) != len(parts):
        raise AppError("funding_amount_mismatch", "各项付款合计必须等于这笔消费的原币金额。", status_code=422)
    return total


def _review_funding_accounts(db: Session, expense: Expense, parts: list[FundingPart], actor_account_id: int
                             ) -> tuple[dict[str, FinancialAccount], dict[int, Debt]]:
    # Account locks always precede the corresponding credit Debt locks.
    accounts = lock_reviewed_accounts(db, ledger_id=expense.tenant_id, actor_account_id=actor_account_id,
        source_account_ids=[], parts=parts)
    debts = dict(db.execute(select(CreditFacility.account_id, Debt).join(Debt, CreditFacility.debt_id == Debt.id)
        .where(CreditFacility.account_id.in_([row.id for row in accounts.values()])).order_by(Debt.id)
        .with_for_update(of=Debt)).all())
    fee = db.get(CreditFeeObligation, expense.id)
    if fee is not None and (len(parts) != 1 or accounts[parts[0].account_public_id].id != fee.account_id
            or parts[0].included_in_opening or expense.original_currency_code != accounts[parts[0].account_public_id].currency_code):
        raise AppError("funding_review_required", "已发生信用费用须保留原信用账户和币种；付款从还款入口清偿，不再改成银行卡消费。", status_code=409)
    for part in parts:
        row = accounts[part.account_public_id]
        validate_funding_currency(part, row, expense.original_currency_code or expense.home_currency_code)
        debt = debts.get(row.id)
        if debt is not None and debt.debt_kind == "one_off" and fee is None:
            raise AppError("invalid_request", "固定本金贷款不能再次作为购物授信；请选择实际付款账户。", status_code=422)
        if part.included_in_opening:
            if not row.balance_known or expense.accounting_date > row.opening_date:
                raise AppError("funding_opening_mismatch", "只有已核对期初范围内的旧消费可以标记为纳入期初。", status_code=422)
        else:
            validate_movement_date(db, row, expense.accounting_date)
    return accounts, debts


def reverse_expense_funding(
    db: Session, *, expense: Expense, actor_account_id: int | None, reason: str,
    occurred_on: date, offset_id: int | None = None,
) -> None:
    facts = list(db.scalars(select(ExpenseFunding).where(ExpenseFunding.expense_id == expense.id,
        ExpenseFunding.voided_at.is_(None))))
    if not facts:
        return
    if actor_account_id is None:
        raise AppError("permission_denied", "请使用付款账户的身份核对本次更正。", status_code=403)
    accounts = lock_reviewed_accounts(db, ledger_id=expense.tenant_id, actor_account_id=actor_account_id,
        source_account_ids=[row.account_id for row in facts], parts=[])
    if offset_id is not None:
        for account in accounts.values():
            validate_movement_date(db, account, occurred_on)
    rows = list(db.scalars(unreversed_movements(select(AccountMovement).where(
        AccountMovement.funding_id.in_([row.id for row in facts])))))
    reverse_movements(db, ledger_id=expense.tenant_id, actor_account_id=actor_account_id, rows=rows,
        reason=reason, occurred_on=occurred_on, offset_id=offset_id)
    for row in facts:
        # Opening coverage is a source link, not a debit. A purchase reversal
        # retains that link for undo and never rewrites the observed opening.
        # Replacing the reviewed funding supersedes it like any other link.
        if offset_id is None or not row.included_in_opening:
            row.voided_at, row.void_reason = now_utc(), reason
    db.flush()


def replace_expense_funding(db, *, expense, actor_account_id, parts, reason, original_accounting_date):
    source_ids = list(db.scalars(select(ExpenseFunding.account_id).where(ExpenseFunding.expense_id == expense.id,
        ExpenseFunding.voided_at.is_(None))))
    accounts = lock_reviewed_accounts(db, ledger_id=expense.tenant_id, actor_account_id=actor_account_id,
        source_account_ids=source_ids, parts=parts)
    reverse_expense_funding(db, expense=expense, actor_account_id=actor_account_id,
        reason=reason, occurred_on=original_accounting_date)
    # Only our own, already reviewed inverse facts have changed these versions under the locks.
    current = [part.model_copy(update={"account_row_version": accounts[part.account_public_id].row_version}) for part in parts]
    publish_expense_funding(db, expense=expense, parts=current, actor_account_id=actor_account_id)


def apply_funding_correction(db, *, expense, before_money, payload, actor_account_id):
    funded = db.scalar(select(ExpenseFunding.id).where(ExpenseFunding.expense_id == expense.id,
        ExpenseFunding.voided_at.is_(None)).limit(1)) is not None
    if funded and before_money != funding_money_identity(expense) and payload.funding is None:
        raise AppError("funding_review_required", "消费已关联资金，请同时核对付款组成；原输入已保留。", status_code=409)
    if payload.funding is not None:
        replace_expense_funding(db, expense=expense, actor_account_id=actor_account_id,
            parts=payload.funding, reason=getattr(payload, "reason", "更正消费付款组成"), original_accounting_date=before_money[3])


def funding_money_identity(expense):
    return (expense.original_currency_code, expense.original_amount_minor, expense.amount_cents, expense.accounting_date)
