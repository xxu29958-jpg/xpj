"""Append linked fund facts within the caller's transaction; never commit here."""
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import aliased

from app.errors import AppError
from app.models import AccountMovement, CreditFacility, CreditSettlementAllocation, Debt, FinancialAccount
from app.services.credit_allocation_service import allocate_credit
from app.services.funds_commands import movement, require_account_version
from app.services.funds_query import account_balance, get_account
from app.services.ledger_calendar_service import current_ledger_date
from app.services.time_service import now_utc


def validate_movement_date(db, account, occurred_on):
    if occurred_on < account.opening_date or occurred_on > current_ledger_date(db, ledger_id=account.tenant_id):
        raise AppError("funds_date_outside_coverage", "实际资金日期须在期初与今天之间；期初已包含的旧消费请选“纳入期初”。", status_code=422)


def refresh_credit(db, account):
    if account.kind != "credit":
        return
    debt = db.scalar(select(Debt).join(CreditFacility, CreditFacility.debt_id == Debt.id)
        .where(CreditFacility.account_id == account.id).with_for_update(of=Debt))
    allocate_credit(db, account)
    debt.row_version += 1
    debt.status = "cleared" if account.balance_known and account_balance(db, account) >= 0 else "open"
    debt.updated_at = now_utc()


def unreversed_movements(query):
    inverse = aliased(AccountMovement)
    return query.where(~select(inverse.id).where(inverse.reversal_of_id == AccountMovement.id).exists())


def lock_reviewed_accounts(db, *, ledger_id, actor_account_id, source_account_ids, parts):
    identifiers = set(db.scalars(select(FinancialAccount.public_id).where(FinancialAccount.id.in_(source_account_ids))))
    identifiers.update(part.account_public_id for part in parts)
    accounts = {identifier: get_account(db, ledger_id=ledger_id, actor_account_id=actor_account_id,
        public_id=identifier, lock=True) for identifier in sorted(identifiers)}
    for part in parts:
        require_account_version(accounts[part.account_public_id], part.account_row_version)
    return accounts


def reverse_movements(db, *, ledger_id, actor_account_id, rows, reason, occurred_on, offset_id=None):
    """Inverse facts also unwind already settled credit without deleting its history."""
    account_ids = {row.account_id for row in rows}
    public_ids = db.scalars(select(FinancialAccount.public_id).where(FinancialAccount.id.in_(account_ids))
        .order_by(FinancialAccount.public_id)).all()
    accounts = {row.id: row for row in [get_account(db, ledger_id=ledger_id, actor_account_id=actor_account_id,
        public_id=public_id, lock=True) for public_id in public_ids]}
    event = str(uuid4())
    for row in rows:
        inverse = movement(db, SimpleNamespace(account_id=actor_account_id), accounts[row.account_id], event=event,
            component=row.public_id, kind="reversal", amount=-row.amount_minor,
            home_amount=-row.home_amount_cents if row.home_amount_cents is not None else None,
            valuation_snapshot=row.valuation_snapshot or {"source": "original_fact", "status": "pending"},
            occurred_on=occurred_on, note=reason[:255], reversal_of_id=row.id, offset_id=offset_id)
        db.flush()
        root = row
        while root.reversal_of_id is not None:
            root = db.get(AccountMovement, root.reversal_of_id)
        for allocation in db.scalars(select(CreditSettlementAllocation).where(
                CreditSettlementAllocation.invalidated_by_movement_id.is_(None),
                or_(CreditSettlementAllocation.credit_movement_id == root.id,
                    CreditSettlementAllocation.draw_movement_id == root.id))):
            allocation.invalidated_by_movement_id = inverse.id
    for account in accounts.values():
        account.row_version += 1
        refresh_credit(db, account)
    db.flush()
