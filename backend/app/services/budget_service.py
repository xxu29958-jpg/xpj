from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Budget, BudgetCategory, RecurringItem
from app.schemas import (
    BudgetCategoryRequest,
    BudgetCategoryResponse,
    BudgetExcludedCategoryResponse,
    BudgetMonthlyResponse,
    BudgetMonthlyUpdateRequest,
)
from app.services.category_service import normalize_category
from app.services.stats_service import _confirmed_query
from app.services.time_service import normalize_month_label, now_utc


@dataclass(frozen=True)
class CategorySpend:
    amount_cents: int = 0
    count: int = 0


def _clean_month(month: str) -> str:
    cleaned = normalize_month_label(month)
    if cleaned is None:
        raise AppError("invalid_request", status_code=422)
    return cleaned


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
        normalized.append((category, int(row.amount_cents)))
        seen.add(category)
    return normalized


def _get_budget(db: Session, *, tenant_id: str, month: str) -> Budget | None:
    return db.scalar(
        ledger_scoped_select(Budget, tenant_id)
        .where(Budget.month == month)
        .limit(1)
    )


def _list_category_budgets(db: Session, *, tenant_id: str, month: str) -> list[BudgetCategory]:
    return list(
        db.scalars(
            ledger_scoped_select(BudgetCategory, tenant_id)
            .where(BudgetCategory.month == month)
            .order_by(BudgetCategory.category.asc(), BudgetCategory.id.asc())
        )
    )


def _active_fixed_amount_cents(db: Session, *, tenant_id: str) -> int:
    amount = db.scalar(
        select(func.coalesce(func.sum(RecurringItem.baseline_amount_cents), 0))
        .where(RecurringItem.tenant_id == tenant_id)
        .where(RecurringItem.frequency == "monthly")
        .where(RecurringItem.status == "active")
    )
    return int(amount or 0)


def _month_spend_by_category(
    db: Session,
    *,
    tenant_id: str,
    month: str,
    timezone_name: str | None,
) -> dict[str, CategorySpend]:
    filtered = _confirmed_query(
        tenant_id=tenant_id,
        month=month,
        timezone_name=timezone_name,
    ).subquery()
    rows = db.execute(
        select(
            filtered.c.category,
            func.coalesce(func.sum(filtered.c.amount_cents), 0),
            func.count(filtered.c.id),
        )
        .select_from(filtered)
        .group_by(filtered.c.category)
    )
    spend: dict[str, CategorySpend] = {}
    for category_value, amount_value, count_value in rows:
        category = normalize_category(category_value)
        current = spend.get(category, CategorySpend())
        spend[category] = CategorySpend(
            amount_cents=current.amount_cents + int(amount_value or 0),
            count=current.count + int(count_value or 0),
        )
    return spend


def _budget_response(
    db: Session,
    *,
    tenant_id: str,
    month: str,
    timezone_name: str | None,
) -> BudgetMonthlyResponse:
    budget = _get_budget(db, tenant_id=tenant_id, month=month)
    category_rows = _list_category_budgets(db, tenant_id=tenant_id, month=month)
    spend_by_category = _month_spend_by_category(
        db,
        tenant_id=tenant_id,
        month=month,
        timezone_name=timezone_name,
    )

    excluded_categories = _parse_excluded_categories(budget.excluded_categories if budget else None)
    excluded_set = set(excluded_categories)
    excluded_breakdown = [
        BudgetExcludedCategoryResponse(
            category=category,
            amount_cents=spend.amount_cents,
            count=spend.count,
        )
        for category, spend in sorted(spend_by_category.items())
        if category in excluded_set
    ]
    excluded_amount_cents = sum(item.amount_cents for item in excluded_breakdown)
    spent_amount_cents = sum(
        spend.amount_cents
        for category, spend in spend_by_category.items()
        if category not in excluded_set
    )

    total_amount_cents = int(budget.total_amount_cents if budget else 0)
    rollover_amount_cents = int(budget.rollover_amount_cents if budget else 0)
    non_monthly_amount_cents = int(budget.non_monthly_amount_cents if budget else 0)
    fixed_amount_cents = _active_fixed_amount_cents(db, tenant_id=tenant_id)
    available_amount_cents = total_amount_cents + rollover_amount_cents
    flex_budget_cents = max(
        available_amount_cents - fixed_amount_cents - non_monthly_amount_cents,
        0,
    )
    remaining_amount_cents = (
        available_amount_cents - spent_amount_cents if budget is not None else 0
    )
    overspent_amount_cents = (
        max(-remaining_amount_cents, 0) if budget is not None else 0
    )

    category_budgets = []
    for category_budget in category_rows:
        category = normalize_category(category_budget.category)
        spent = spend_by_category.get(category, CategorySpend()).amount_cents
        remaining = int(category_budget.amount_cents) - spent
        category_budgets.append(
            BudgetCategoryResponse(
                category=category,
                amount_cents=int(category_budget.amount_cents),
                spent_amount_cents=spent,
                remaining_amount_cents=remaining,
                overspent_amount_cents=max(-remaining, 0),
            )
        )

    return BudgetMonthlyResponse(
        ledger_id=tenant_id,
        month=month,
        configured=budget is not None,
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
            key=lambda item: item.amount_cents,
            reverse=True,
        ),
        category_budgets=category_budgets,
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


def upsert_monthly_budget(
    db: Session,
    *,
    tenant_id: str,
    month: str,
    payload: BudgetMonthlyUpdateRequest,
    timezone_name: str | None = None,
) -> BudgetMonthlyResponse:
    clean_month = _clean_month(month)
    excluded_categories = _clean_excluded_categories(payload.excluded_categories)
    category_budget_rows = _clean_category_budget_rows(payload.category_budgets)
    now = now_utc()

    budget = _get_budget(db, tenant_id=tenant_id, month=clean_month)
    if budget is None:
        budget = Budget(
            tenant_id=tenant_id,
            month=clean_month,
            created_at=now,
        )
        db.add(budget)
    budget.total_amount_cents = int(payload.total_amount_cents)
    budget.non_monthly_amount_cents = int(payload.non_monthly_amount_cents)
    budget.rollover_amount_cents = int(payload.rollover_amount_cents)
    budget.excluded_categories = _serialize_excluded_categories(excluded_categories)
    budget.updated_at = now

    existing = {
        row.category: row
        for row in _list_category_budgets(db, tenant_id=tenant_id, month=clean_month)
    }
    requested_categories = {category for category, _ in category_budget_rows}
    for category, amount_cents in category_budget_rows:
        row = existing.get(category)
        if row is None:
            row = BudgetCategory(
                tenant_id=tenant_id,
                month=clean_month,
                category=category,
                created_at=now,
            )
            db.add(row)
        row.amount_cents = amount_cents
        row.updated_at = now

    for category, row in existing.items():
        if category not in requested_categories:
            db.delete(row)

    try:
        db.flush()
        response = _budget_response(
            db,
            tenant_id=tenant_id,
            month=clean_month,
            timezone_name=timezone_name,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return response
