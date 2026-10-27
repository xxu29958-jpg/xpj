"""Append linked fund facts within the caller's transaction; never commit here."""
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import literal, or_, select
from sqlalchemy.orm import Session, aliased

from app.errors import AppError
from app.models import AccountMovement, CreditFacility, CreditSettlementAllocation, Debt, FinancialAccount
from app.services.credit_allocation_service import active_allocation_condition, allocate_credit
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
    refresh_credit_debt(db, account, debt)


def refresh_credit_debt(db: Session, account: FinancialAccount, debt: Debt) -> None:
    """Refresh the credit Debt once after its caller has locked and changed the funds facts."""
    debt.row_version += 1
    debt.status = "cleared" if account.balance_known and account_balance(db, account) >= 0 else "open"
    debt.updated_at = now_utc()


def unreversed_movements(query):
    """Return active leaves, including facts restored by an inverse of an inverse."""
    lineage = query.with_only_columns(AccountMovement.id.label("movement_id"), literal(0).label("depth")).cte(
        "funds_reversal_lineage", recursive=True)
    child = aliased(AccountMovement)
    lineage = lineage.union_all(select(child.id, lineage.c.depth + 1)
        .join(lineage, child.reversal_of_id == lineage.c.movement_id))
    inverse = aliased(AccountMovement)
    active = select(lineage.c.movement_id).where(lineage.c.depth % 2 == 0,
        ~select(inverse.id).where(inverse.reversal_of_id == lineage.c.movement_id).exists())
    return select(AccountMovement).where(AccountMovement.id.in_(active))


def lock_reviewed_accounts(db, *, ledger_id, actor_account_id, source_account_ids, parts):
    identifiers = set(db.scalars(select(FinancialAccount.public_id).where(FinancialAccount.id.in_(source_account_ids))))
    identifiers.update(part.account_public_id for part in parts)
    accounts = {identifier: get_account(db, ledger_id=ledger_id, actor_account_id=actor_account_id,
        public_id=identifier, lock=True) for identifier in sorted(identifiers)}
    for part in parts:
        require_account_version(accounts[part.account_public_id], part.account_row_version)
    return accounts


def reverse_movements(db: Session, *, ledger_id: str, actor_account_id: int, rows: list[AccountMovement],
                      reason: str, occurred_on: date, offset_id: int | None = None) -> dict[int, int]:
    """Inverse facts also unwind already settled credit without deleting its history."""
    account_ids = {row.account_id for row in rows}
    public_ids = db.scalars(select(FinancialAccount.public_id).where(FinancialAccount.id.in_(account_ids))
        .order_by(FinancialAccount.public_id)).all()
    accounts = {row.id: row for row in [get_account(db, ledger_id=ledger_id, actor_account_id=actor_account_id,
        public_id=public_id, lock=True) for public_id in public_ids]}
    if offset_id is not None:  # A new expense reversal chooses a date; undo preserves the original fact's date.
        for account in accounts.values():
            validate_movement_date(db, account, occurred_on)
    roots, allocations = _reversed_allocations(db, rows, account_ids)
    event = str(uuid4())
    for row in rows:
        inverse = movement(db, SimpleNamespace(account_id=actor_account_id), accounts[row.account_id], event=event,
            component=row.public_id, kind="reversal", amount=-row.amount_minor,
            home_amount=-row.home_amount_cents if row.home_amount_cents is not None else None,
            valuation_snapshot=row.valuation_snapshot or {"source": "original_fact", "status": "pending"},
            occurred_on=occurred_on, note=reason[:255], reversal_of_id=row.id, offset_id=offset_id)
        db.flush()
        for allocation in allocations.get(roots[row.id], []):
            if allocation.invalidated_by_movement_id is None:
                allocation.invalidated_by_movement_id = inverse.id
    for account in accounts.values():
        account.row_version += 1
        refresh_credit(db, account)
    db.flush()
    return roots


def _reversed_allocations(db: Session, rows: list[AccountMovement], account_ids: set[int]
                          ) -> tuple[dict[int, int], dict[int, list[CreditSettlementAllocation]]]:
    lineage = dict(db.execute(select(AccountMovement.id, AccountMovement.reversal_of_id)
        .where(AccountMovement.account_id.in_(account_ids))).all())
    roots = {}
    for row in rows:
        root = row.id
        while lineage[root] is not None:
            root = lineage[root]
        roots[row.id] = root
    affected = set(roots.values())
    allocations: dict[int, list[CreditSettlementAllocation]] = {}
    for allocation in db.scalars(select(CreditSettlementAllocation).where(
            active_allocation_condition(),
            or_(CreditSettlementAllocation.credit_movement_id.in_(affected),
                CreditSettlementAllocation.draw_movement_id.in_(affected)))):
        for identifier in {allocation.credit_movement_id, allocation.draw_movement_id} & affected:
            allocations.setdefault(identifier, []).append(allocation)
    return roots, allocations
