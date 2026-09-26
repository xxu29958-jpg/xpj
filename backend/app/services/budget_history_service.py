"""Record within the existing budget transaction; read by ledger/month and version."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Budget, BudgetCategory, BudgetRevision
from app.schemas._budget_history import BudgetHistoryResponse, BudgetRevisionResponse, BudgetSnapshot
from app.services.budget_categories import parse_budget_exclusions
from app.services.category_common import normalize_category
from app.services.spending_contract_service import clean_month
from app.services.time_service import now_utc


def record_budget_revision(db: Session, budget: Budget, *, change_kind: str, actor_account_id: int | None = None) -> None:
    categories = db.scalars(select(BudgetCategory).where(
        BudgetCategory.tenant_id == budget.tenant_id, BudgetCategory.month == budget.month,
    ).order_by(BudgetCategory.category, BudgetCategory.id)).all()
    snapshot = BudgetSnapshot(
        home_currency_code=budget.home_currency_code,
        total_amount_cents=budget.total_amount_cents,
        non_monthly_amount_cents=budget.non_monthly_amount_cents,
        rollover_amount_cents=budget.rollover_amount_cents,
        excluded_categories=parse_budget_exclusions(budget.excluded_categories),
        category_budgets=[{"category": normalize_category(row.category), "amount_cents": row.amount_cents} for row in categories],
        archived=budget.archived_at is not None,
    )
    db.add(BudgetRevision(tenant_id=budget.tenant_id, budget_id=budget.id, row_version=budget.row_version,
        change_kind=change_kind, snapshot=snapshot.model_dump(mode="json"),
        actor_account_id=actor_account_id, recorded_at=now_utc()))


def budget_history(db: Session, *, tenant_id: str, month: str,
    before_version: int | None = None, limit: int = 20) -> BudgetHistoryResponse:
    month = clean_month(month)
    query = select(BudgetRevision).join(Budget,
        (Budget.id == BudgetRevision.budget_id) & (Budget.tenant_id == BudgetRevision.tenant_id),
    ).where(Budget.tenant_id == tenant_id, Budget.month == month)
    if before_version is not None:
        query = query.where(BudgetRevision.row_version < before_version)
    rows = db.scalars(query.order_by(BudgetRevision.row_version.desc()).limit(limit + 1)).all()
    selected = rows[:limit]
    return BudgetHistoryResponse(ledger_id=tenant_id, month=month,
        items=[BudgetRevisionResponse(row_version=row.row_version, change_kind=row.change_kind,
            recorded_at=row.recorded_at, snapshot=BudgetSnapshot.model_validate(row.snapshot)) for row in selected],
        next_before_version=selected[-1].row_version if len(rows) > limit else None)
