"""Cash available for purposes, reusing current budgets and confirmed financial facts."""
from collections import defaultdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AccountMovement,
    Budget,
    BudgetCategory,
    EnvelopeAllocation,
    EnvelopeBook,
    EnvelopeRevision,
    EnvelopeSource,
    FinancialAccount,
    MonthlyArrangement,
)
from app.schemas.envelopes import (
    EnvelopeAccountView,
    EnvelopeMonthView,
    EnvelopePurposeView,
    EnvelopeRevisionView,
    EnvelopesView,
)
from app.services.currency_binding_service import require_runtime_home_currency_code
from app.services.envelope_spending import EnvelopeSpending, spending_by_purpose
from app.services.funds_visibility import account_scope
from app.services.ledger_calendar_service import current_ledger_date
from app.services.money_projection_service import project_recorded_amount, sum_projected_amounts
from app.services.spending_contract_service import clean_month
from app.services.spending_projection_service import read_purchase_spending
from app.services.time_service import now_utc

PURPOSE_LABELS = {"spending": "其他消费", "savings": "储蓄", "buffer": "备用金"}


def _plan_targets(db: Session, *, tenant_id: str, month: str, home: str) -> dict[str, int | None]:
    budget = db.scalar(select(Budget).where(Budget.tenant_id == tenant_id, Budget.month == month,
                                          Budget.archived_at.is_(None)))
    categories = list(db.scalars(select(BudgetCategory).where(BudgetCategory.tenant_id == tenant_id,
                                                             BudgetCategory.month == month))) if budget else []
    arrangement = db.scalar(select(MonthlyArrangement).where(MonthlyArrangement.tenant_id == tenant_id,
                                                            MonthlyArrangement.month == month))
    values = {"spending": (None, home), "savings": (None, home), "buffer": (None, home)}
    if budget:
        values["spending"] = (max(0, budget.total_amount_cents + budget.rollover_amount_cents -
                                  sum(row.amount_cents for row in categories)), budget.home_currency_code)
        values.update({"category:" + row.category: (row.amount_cents, budget.home_currency_code) for row in categories})
    if arrangement:
        values.update(savings=(arrangement.savings_target_cents, arrangement.home_currency_code),
                      buffer=(arrangement.reserved_buffer_cents, arrangement.home_currency_code))
    rates: dict = {}
    return {key: None if amount is None else project_recorded_amount(db, tenant_id=tenant_id, amount_minor=amount, source_currency=currency,
                home_currency=home, rate_date=date.fromisoformat(month + "-01"), missing_rates=set(), rate_cache=rates)
            for key, (amount, currency) in values.items()}


def _cash_accounts(db: Session, *, tenant_id: str, actor_account_id: int, home: str, today: date
                   ) -> tuple[list[EnvelopeAccountView], int | None]:
    selected = set(db.scalars(select(EnvelopeSource.account_id).where(EnvelopeSource.tenant_id == tenant_id)))
    accounts = list(db.scalars(select(FinancialAccount).where(FinancialAccount.tenant_id == tenant_id,
        FinancialAccount.visibility == "ledger", FinancialAccount.kind != "credit").order_by(FinancialAccount.id)))
    balances = dict(db.execute(select(AccountMovement.account_id, func.sum(AccountMovement.amount_minor)).where(
        AccountMovement.account_id.in_([row.id for row in accounts]), AccountMovement.occurred_on <= today)
        .group_by(AccountMovement.account_id)).all())
    result, cash, rates = [], [], {}
    for account in accounts:
        balance = int(balances.get(account.id, 0)) if account.balance_known and account.opening_date <= today else None
        result.append(EnvelopeAccountView(public_id=account.public_id, name=account.name,
            currency_code=account.currency_code, balance_minor=balance, row_version=account.row_version,
            selected=account.id in selected, can_select=account.owner_account_id == actor_account_id and
                (account.archived_at is None or account.id in selected)))
        if account.id in selected:
            cash.append(None if balance is None else project_recorded_amount(db, tenant_id=tenant_id, amount_minor=balance,
                source_currency=account.currency_code, home_currency=home, rate_date=today, missing_rates=set(), rate_cache=rates))
    if selected - {row.id for row in accounts}:
        cash.append(None)
    return result, sum_projected_amounts(cash, label="envelope.cash")


def _purpose(key: str, amount: int | None, planned: int | None, spending: EnvelopeSpending) -> EnvelopePurposeView:
    available = None if amount is None or spending.spent is None else amount - spending.spent
    pending = sum_projected_amounts((spending.unpaid, spending.unlinked), label="envelope.pending")
    reserved = None if available is None or pending is None else max(0, available + pending)
    return EnvelopePurposeView(purpose=key, label=PURPOSE_LABELS.get(key, key.removeprefix("category:")),
        planned_minor=planned, funded=amount is not None, allocated_minor=amount or 0,
        spent_minor=spending.spent, unpaid_credit_minor=spending.unpaid, unlinked_minor=spending.unlinked,
        available_minor=available, reserved_minor=0 if amount is None else reserved)


def _monthly_reservations(months, month, amounts, targets, spending):
    month_views, purposes = [], []
    for value in months:
        keys = {key for (row_month, key) in amounts if row_month == value}
        selected_targets = targets if value == month else {}
        keys.update(selected_targets)
        rows = [_purpose(key, amounts.get((value, key)), selected_targets.get(key),
                         spending.get((value, key), EnvelopeSpending())) for key in sorted(keys)]
        month_views.append(EnvelopeMonthView(month=value, reserved_minor=sum_projected_amounts(
            (row.reserved_minor for row in rows), label="envelope.month_reserved")))
        if value == month:
            purposes = rows
    return month_views, purposes


def envelopes_view(db: Session, *, tenant_id: str, actor_account_id: int, month: str) -> EnvelopesView:
    month = clean_month(month)
    book = db.get(EnvelopeBook, tenant_id)
    home = book.home_currency_code if book else require_runtime_home_currency_code(db)
    today = current_ledger_date(db, ledger_id=tenant_id)
    allocations = list(db.scalars(select(EnvelopeAllocation).where(EnvelopeAllocation.tenant_id == tenant_id)))
    months = sorted({month, *(row.month for row in allocations)})
    categories: dict[str, set[str]] = defaultdict(set)
    amounts = {(row.month, row.purpose): row.allocated_minor for row in allocations}
    for row in allocations:
        if row.purpose.startswith("category:"):
            categories[row.month].add(row.purpose)
    purchases = read_purchase_spending(db, tenant_id=tenant_id, months=months, home=home, as_of=today)
    spending = spending_by_purpose(db, tenant_id=tenant_id, home=home, purchases=purchases, category_purposes=categories)
    targets = _plan_targets(db, tenant_id=tenant_id, month=month, home=home)
    accounts, cash = _cash_accounts(db, tenant_id=tenant_id, actor_account_id=actor_account_id, home=home, today=today)
    month_views, purposes = _monthly_reservations(months, month, amounts, targets, spending)
    reserved = sum_projected_amounts((row.reserved_minor for row in month_views), label="envelope.reserved")
    notices = _notices(cash, reserved, purchases)
    if any(row.month is None and row.amount_minor != 0 for row in purchases):
        reserved = None
    return EnvelopesView(ledger_id=tenant_id, month=month, home_currency_code=home, row_version=book.row_version if book else 0,
        read_at=now_utc(), valuation_date=today, cash_minor=cash, reserved_minor=reserved,
        unassigned_minor=None if cash is None or reserved is None else cash - reserved,
        accounts=accounts, purposes=purposes, months=month_views, notices=notices)


def _notices(cash: int | None, reserved: int | None, purchases: list) -> list[str]:
    messages = []
    if cash is None:
        messages.append("所选账户有未核对余额、待补汇率或已不可见的账户；可分配现金尚未确定。")
    if reserved is None:
        messages.append("消费金额或汇率尚未补齐，已留出的现金不能当作剩余资金。")
    if any(row.month is None and row.amount_minor != 0 for row in purchases):
        messages.append("有消费尚未填写账务日期，不能确定它占用哪个月的信封。")
    return messages


def redact_envelope_snapshot(snapshot: dict, visible_account_ids: set[str]) -> dict:
    sources = snapshot["account_public_ids"]
    visible = [identifier for identifier in sources if identifier in visible_account_ids]
    if len(visible) == len(sources):
        return snapshot
    return {**snapshot, "account_public_ids": visible, "hidden_account_count": len(sources) - len(visible)}


def envelope_history(db: Session, *, tenant_id: str, actor_account_id: int,
        before_version: int | None = None) -> list[EnvelopeRevisionView]:
    query = select(EnvelopeRevision).where(EnvelopeRevision.tenant_id == tenant_id)
    if before_version is not None:
        query = query.where(EnvelopeRevision.row_version < before_version)
    visible = set(db.scalars(select(FinancialAccount.public_id).where(account_scope(tenant_id, actor_account_id))))
    return [EnvelopeRevisionView(row_version=row.row_version, month=row.month, reason=row.reason,
        allocation_snapshot=redact_envelope_snapshot(row.allocation_snapshot, visible), recorded_at=row.recorded_at)
        for row in db.scalars(query.order_by(EnvelopeRevision.row_version.desc()).limit(20))]
