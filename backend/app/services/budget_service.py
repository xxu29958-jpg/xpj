from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Budget, BudgetCategory
from app.money_contract import (
    MoneySign,
    ensure_money_minor,
    projection_sum_to_int,
    projection_values_sum_to_int,
)
from app.schemas import (
    BudgetCategoryRequest,
    BudgetCategoryResponse,
    BudgetExcludedCategoryResponse,
    BudgetMonthlyResponse,
)
from app.services.budget_money import (
    budget_amount_breakdown as _budget_amount_breakdown,
)
from app.services.category_service import normalize_category
from app.services.currency_binding_service import (
    require_runtime_home_currency_code,
    resolve_write_capability,
)
from app.services.money_projection_service import project_recorded_amount
from app.services.optimistic_concurrency import claim_row_with_token
from app.services.recurring_service import recurring_monthly_total
from app.services.spending_contract_service import (
    clean_month,
    confirmed_amount_query,
    monthly_recurring_items_query,
)
from app.services.time_service import now_utc


@dataclass(frozen=True)
class CategorySpend:
    amount_cents: int | None = 0
    count: int = 0


def _clean_month(month: str) -> str:
    return clean_month(month)


def _clean_category(value: str) -> str:
    raw = (value or "").strip()
    if not raw or len(raw) > 64:
        raise AppError("invalid_request", status_code=422)
    return normalize_category(raw)


def _serialize_excluded_categories(categories: list[str]) -> str:
    return json.dumps(categories, ensure_ascii=False, separators=(",", ":"))


def _parse_excluded_categories(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in parsed:
        if not isinstance(item, str):
            continue
        try:
            category = _clean_category(item)
        except AppError:
            continue
        if category not in seen:
            normalized.append(category)
            seen.add(category)
    return normalized


def _clean_excluded_categories(categories: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in categories:
        category = _clean_category(item)
        if category in seen:
            continue
        normalized.append(category)
        seen.add(category)
    return normalized


def _clean_category_budget_rows(rows: list[BudgetCategoryRequest]) -> list[tuple[str, int]]:
    normalized: list[tuple[str, int]] = []
    seen: set[str] = set()
    for row in rows:
        category = _clean_category(row.category)
        if category in seen:
            raise AppError("invalid_request", status_code=422)
        amount_cents = ensure_money_minor(
            row.amount_cents,
            sign=MoneySign.NONNEGATIVE,
            label="budget_category.amount_cents",
        )
        normalized.append((category, amount_cents))
        seen.add(category)
    return normalized


def _get_budget(db: Session, *, tenant_id: str, month: str) -> Budget | None:
    return db.scalar(
        ledger_scoped_select(Budget, tenant_id)
        .where(Budget.month == month)
        .where(Budget.archived_at.is_(None))
        .limit(1)
    )


def _get_any_budget(db: Session, *, tenant_id: str, month: str) -> Budget | None:
    return db.scalar(ledger_scoped_select(Budget, tenant_id).where(Budget.month == month).limit(1))


def _require_budget(db: Session, *, tenant_id: str, month: str) -> Budget:
    budget = _get_any_budget(db, tenant_id=tenant_id, month=month)
    if budget is None:
        raise AppError("budget_not_found", "没有找到这月预算。", status_code=404)
    return budget


def _list_category_budgets(db: Session, *, tenant_id: str, month: str) -> list[BudgetCategory]:
    return list(
        db.scalars(
            ledger_scoped_select(BudgetCategory, tenant_id)
            .where(BudgetCategory.month == month)
            .order_by(BudgetCategory.category.asc(), BudgetCategory.id.asc())
        )
    )


def list_archived_budgets(db: Session, *, tenant_id: str) -> list[Budget]:
    return list(
        db.scalars(
            ledger_scoped_select(Budget, tenant_id)
            .where(Budget.archived_at.is_not(None))
            .order_by(Budget.archived_at.desc(), Budget.id.desc())
        )
    )


def _fixed_amount_cents_for_month(
    db: Session,
    *,
    tenant_id: str,
    month: str,
    timezone_name: str | None,
    home_currency_code: str,
) -> int | None:
    items = db.scalars(
        monthly_recurring_items_query(
            tenant_id=tenant_id,
            month=month,
            timezone_name=timezone_name,
        )
    )
    return recurring_monthly_total(db, tenant_id=tenant_id, items=items, home_currency_code=home_currency_code, month=month)


def _month_spend_by_category(
    db: Session,
    *,
    tenant_id: str,
    month: str,
    timezone_name: str | None,
    home_currency_code: str,
) -> tuple[dict[str, CategorySpend], set[str]]:
    rows = db.execute(confirmed_amount_query(
        tenant_id=tenant_id,
        month=month,
        timezone_name=timezone_name,
    ))
    return _project_category_spend(db, tenant_id=tenant_id, home=home_currency_code, rows=rows)


def _project_category_spend(db: Session, *, tenant_id: str, home: str, rows) -> tuple[dict[str, CategorySpend], set[str]]:
    spend: dict[str, CategorySpend] = {}
    missing: set[str] = set()
    for row in rows:
        category = normalize_category(row.category)
        current = spend.get(category, CategorySpend())
        amount = project_recorded_amount(db, tenant_id=tenant_id, amount_minor=row.amount_cents,
            source_currency=row.home_currency_code, home_currency=home, rate_date=row.stream_date)
        if amount is None:
            missing.add(row.home_currency_code or "UNKNOWN")
        spend[category] = CategorySpend(
            amount_cents=_sum_known((current.amount_cents, amount), label="budget.category_spend_total"),
            count=current.count + 1,
        )
    return spend, missing


def _sum_known(values, *, label: str) -> int | None:
    amounts = list(values)
    if any(amount is None for amount in amounts):
        return None
    return projection_values_sum_to_int(amounts, label=label)


def _build_excluded_breakdown(
    spend_by_category: dict[str, CategorySpend], excluded_set: set[str]
) -> tuple[list[BudgetExcludedCategoryResponse], int | None]:
    breakdown = [
        BudgetExcludedCategoryResponse(
            category=category,
            amount_cents=spend.amount_cents,
            count=spend.count,
        )
        for category, spend in sorted(spend_by_category.items())
        if category in excluded_set
    ]
    return breakdown, _sum_known(
        (item.amount_cents for item in breakdown),
        label="budget.excluded_total",
    )


def _build_category_budgets(category_rows, spend_by_category: dict[str, CategorySpend]) -> list[BudgetCategoryResponse]:
    out: list[BudgetCategoryResponse] = []
    for category_budget in category_rows:
        category = normalize_category(category_budget.category)
        spent = spend_by_category.get(category, CategorySpend()).amount_cents
        amount_cents = projection_sum_to_int(
            category_budget.amount_cents,
            label="budget.category_limit",
        )
        remaining = None if spent is None else projection_sum_to_int(
            amount_cents - spent,
            label="budget.category_remaining",
        )
        out.append(
            BudgetCategoryResponse(
                category=category,
                amount_cents=amount_cents,
                spent_amount_cents=spent,
                remaining_amount_cents=remaining,
                overspent_amount_cents=None if remaining is None else max(-remaining, 0),
            )
        )
    return out


def _budget_response(
    db: Session,
    *,
    tenant_id: str,
    month: str,
    timezone_name: str | None,
) -> BudgetMonthlyResponse:
    budget = _get_budget(db, tenant_id=tenant_id, month=month)
    home = budget.home_currency_code if budget else require_runtime_home_currency_code(db)
    category_rows = _list_category_budgets(db, tenant_id=tenant_id, month=month) if budget is not None else []
    spend_by_category, missing = _month_spend_by_category(db, tenant_id=tenant_id, month=month,
        timezone_name=timezone_name, home_currency_code=home)
    excluded_categories = _parse_excluded_categories(budget.excluded_categories if budget else None)
    excluded_set = set(excluded_categories)
    excluded_breakdown, excluded_amount_cents = _build_excluded_breakdown(spend_by_category, excluded_set)
    spent_amount_cents = _sum_known(
        (spend.amount_cents for category, spend in spend_by_category.items() if category not in excluded_set),
        label="budget.spent_total",
    )
    fixed_amount_cents = _fixed_amount_cents_for_month(
        db, tenant_id=tenant_id, month=month, timezone_name=timezone_name, home_currency_code=home
    )
    if fixed_amount_cents is None:
        missing.add("UNKNOWN")
    (
        total_amount_cents,
        rollover_amount_cents,
        non_monthly_amount_cents,
        flex_budget_cents,
        remaining_amount_cents,
        overspent_amount_cents,
    ) = _budget_amount_breakdown(
        budget,
        fixed_amount_cents=fixed_amount_cents,
        spent_amount_cents=spent_amount_cents,
    )

    return BudgetMonthlyResponse(
        ledger_id=tenant_id,
        home_currency_code=home,
        missing_currency_codes=sorted(missing),
        month=month,
        configured=budget is not None,
        row_version=budget.row_version if budget else None,
        total_amount_cents=total_amount_cents,
        rollover_amount_cents=rollover_amount_cents,
        fixed_amount_cents=fixed_amount_cents,
        non_monthly_amount_cents=non_monthly_amount_cents,
        flex_budget_cents=flex_budget_cents,
        spent_amount_cents=spent_amount_cents,
        excluded_amount_cents=excluded_amount_cents,
        remaining_amount_cents=remaining_amount_cents,
        overspent_amount_cents=overspent_amount_cents,
        excluded_categories=excluded_categories,
        excluded_breakdown=sorted(
            excluded_breakdown,
            key=lambda item: (item.amount_cents is not None, item.amount_cents or 0),
            reverse=True,
        ),
        category_budgets=_build_category_budgets(category_rows, spend_by_category),
        updated_at=budget.updated_at if budget else None,
    )


def get_monthly_budget(
    db: Session,
    *,
    tenant_id: str,
    month: str,
    timezone_name: str | None = None,
) -> BudgetMonthlyResponse:
    clean_month = _clean_month(month)
    return _budget_response(
        db,
        tenant_id=tenant_id,
        month=clean_month,
        timezone_name=timezone_name,
    )


def archive_monthly_budget(
    db: Session,
    *,
    tenant_id: str,
    month: str,
    expected_row_version: int,
) -> Budget:
    clean_month = _clean_month(month)
    budget = _require_budget(db, tenant_id=tenant_id, month=clean_month)
    if budget.archived_at is not None:
        return budget
    resolve_write_capability(db)
    now = now_utc()
    rowcount = claim_row_with_token(
        db,
        Budget,
        pk_id=budget.id,
        tenant_id=tenant_id,
        expected_row_version=expected_row_version,
        set_values={"archived_at": now, "updated_at": now},
        extra_where=(Budget.archived_at.is_(None),),
        synchronize_session=False,
    )
    if rowcount != 1:
        db.rollback()
        current = _require_budget(db, tenant_id=tenant_id, month=clean_month)
        if current.archived_at is not None:
            return current
        raise AppError("state_conflict", status_code=409)
    db.commit()
    db.expire_all()
    return _require_budget(db, tenant_id=tenant_id, month=clean_month)


def restore_monthly_budget(
    db: Session,
    *,
    tenant_id: str,
    month: str,
    expected_row_version: int,
) -> Budget:
    clean_month = _clean_month(month)
    budget = _require_budget(db, tenant_id=tenant_id, month=clean_month)
    if budget.archived_at is None:
        return budget
    resolve_write_capability(db)
    now = now_utc()
    rowcount = claim_row_with_token(
        db,
        Budget,
        pk_id=budget.id,
        tenant_id=tenant_id,
        expected_row_version=expected_row_version,
        set_values={"archived_at": None, "updated_at": now},
        extra_where=(Budget.archived_at.is_not(None),),
        synchronize_session=False,
    )
    if rowcount != 1:
        db.rollback()
        current = _require_budget(db, tenant_id=tenant_id, month=clean_month)
        if current.archived_at is None:
            return current
        raise AppError("state_conflict", status_code=409)
    db.commit()
    db.expire_all()
    return _require_budget(db, tenant_id=tenant_id, month=clean_month)
