"""Expense offsets and their actual refund destinations publish atomically."""
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import AccountMovement, Expense, ExpenseFunding, ExpenseOffsetFact
from app.schemas.funds import RefundDestination
from app.services.expense_funding_service import reverse_expense_funding
from app.services.funds_commands import movement, require_account_version
from app.services.funds_fact_service import (
    refresh_credit,
    reverse_movements,
    unreversed_movements,
    validate_movement_date,
)
from app.services.funds_query import get_account
from app.services.installment_query import draw_balances


def apply_offset_funds(db: Session, *, expense: Expense, offset: ExpenseOffsetFact,
        destinations: list[RefundDestination] | None, actor_account_id: int) -> None:
    if offset.kind == "reversal":
        if destinations:
            raise AppError("invalid_request", "冲正按原付款来源撤销，请勿同时填写退款去向。", status_code=422)
        reverse_expense_funding(db, expense=expense, actor_account_id=actor_account_id, reason=offset.reason,
            occurred_on=offset.accounting_date, offset_id=offset.id)
        return
    has_funding = db.scalar(select(ExpenseFunding.id).where(ExpenseFunding.expense_id == expense.id,
        ExpenseFunding.voided_at.is_(None)).limit(1)) is not None
    if not destinations:
        if has_funding:
            raise AppError("refund_destination_required", "请选择实际退入的账户；申请中的退款先保留原稿，到账后再确认。", status_code=422)
        return
    if sum(row.original_amount_minor for row in destinations) != offset.original_amount_minor:
        raise AppError("funding_amount_mismatch", "退款各去向的原币合计须等于本次退款金额。", status_code=422)
    accounts = {pid: get_account(db, ledger_id=expense.tenant_id, actor_account_id=actor_account_id,
        public_id=pid, lock=True) for pid in sorted({row.account_public_id for row in destinations})}
    event = str(uuid4())
    for index, part in enumerate(destinations):
        account = accounts[part.account_public_id]
        require_account_version(account, part.account_row_version)
        validate_movement_date(db, account, offset.accounting_date)
        if account.currency_code == offset.original_currency_code and part.received_amount_minor != part.original_amount_minor:
            raise AppError("funding_amount_mismatch", "同币种实际退款与去向金额应一致。", status_code=422)
        targets = refund_credit_targets(db, account, expense.id, part.received_amount_minor) if account.kind == "credit" else None
        movement(db, SimpleNamespace(account_id=actor_account_id), account, event=event, component=str(index),
            kind="refund", amount=part.received_amount_minor, occurred_on=offset.accounting_date,
            note=offset.reason[:255], offset_id=offset.id, settlement_targets=targets)
    for account in accounts.values():
        account.row_version += 1
        refresh_credit(db, account)


def refund_credit_targets(db, account, expense_id, amount):
    """A refund belongs to its purchase; another purchase is not silently treated as settled."""
    balances = draw_balances(db, account.id)
    result = {}
    for row in db.scalars(select(AccountMovement).join(ExpenseFunding, ExpenseFunding.id == AccountMovement.funding_id)
            .where(AccountMovement.account_id == account.id, ExpenseFunding.expense_id == expense_id)
            .order_by(AccountMovement.id)):
        take = min(amount, balances.get(row.id, 0))
        if take > 0:
            result[str(row.id)] = take
            amount -= take
    return result


def reverse_offset_funds(db, *, expense, offset, actor_account_id, reason):
    rows = list(db.scalars(unreversed_movements(select(AccountMovement).where(AccountMovement.offset_id == offset.id))))
    reverse_movements(db, ledger_id=expense.tenant_id, actor_account_id=actor_account_id, rows=rows,
        reason=reason, occurred_on=offset.accounting_date)
    if offset.kind == "reversal":
        for funding in db.scalars(select(ExpenseFunding).join(AccountMovement, AccountMovement.funding_id == ExpenseFunding.id)
                .where(AccountMovement.id.in_([row.reversal_of_id for row in rows]))):
            funding.voided_at = None
