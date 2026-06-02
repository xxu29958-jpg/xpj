from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import CategoryRule, Expense
from app.schemas import ExpenseUpdateRequest
from app.services.category_common import (
    DEFAULT_CATEGORIES,
    LEGACY_CATEGORY_ALIASES,
    category_filter_values,
    normalize_category,
)
from app.services.spending_contract_service import month_bounds_utc, stat_time_expr

# Re-exports — existing callers do
# ``from app.services.category_service import normalize_category`` etc.
# Keep that surface stable.
__all_category_helpers = (
    DEFAULT_CATEGORIES,
    LEGACY_CATEGORY_ALIASES,
    category_filter_values,
    normalize_category,
)


def category_sort_key(value: str) -> tuple[int, int | str]:
    normalized = normalize_category(value)
    if normalized in DEFAULT_CATEGORIES:
        return (0, DEFAULT_CATEGORIES.index(normalized))
    return (1, normalized)


def merge_categories(values: list[str]) -> list[str]:
    categories = {normalize_category(item) for item in values if item and item.strip()}
    categories.update(DEFAULT_CATEGORIES)
    return sorted(categories, key=category_sort_key)


def normalize_existing_expense_categories(db: Session, tenant_id: str) -> None:
    changed = False
    expenses = db.scalars(
        select(Expense)
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.category.in_(LEGACY_CATEGORY_ALIASES.keys()))
    )
    for expense in expenses:
        normalized = normalize_category(expense.category)
        if normalized != expense.category:
            expense.category = normalized
            changed = True
    rules = db.scalars(
        select(CategoryRule)
        .where(CategoryRule.tenant_id == tenant_id)
        .where(CategoryRule.deleted_at.is_(None))
        .where(CategoryRule.category.in_(LEGACY_CATEGORY_ALIASES.keys()))
    )
    for rule in rules:
        normalized = normalize_category(rule.category)
        if normalized != rule.category:
            rule.category = normalized
            changed = True
    if changed:
        db.commit()

# ── /web/categories dashboard (v0.4-alpha3 slice 2 / M3 / T12-T13) ─────────


# Categories considered "uncategorized" for the cleanup workflow.
UNCATEGORIZED_CATEGORIES: tuple[str, ...] = ("", "其他", "未分类")


@dataclass
class CategorySummary:
    category: str
    confirmed_count: int
    pending_count: int
    confirmed_amount_cents: int
    is_uncategorized: bool


@dataclass
class CategoryDashboard:
    month: str
    summaries: list[CategorySummary] = field(default_factory=list)
    rule_count: int = 0
    uncategorized_pending: int = 0


def list_category_summary(
    db: Session, *, tenant_id: str, month: str, timezone_name: str | None = None
) -> CategoryDashboard:
    """Return per-category counts/amounts for the dashboard.

    Confirmed amounts/counts are scoped to ``[start, end)`` of ``month``
    based on expense time first, then confirmed time. Pending counts are global per category so
    the user can see lingering uncategorized rows regardless of month.
    """
    start, end = month_bounds_utc(month, timezone_name)
    stat_time = stat_time_expr()

    confirmed_rows = db.execute(
        select(
            Expense.category,
            func.count(Expense.id),
            func.coalesce(func.sum(Expense.amount_cents), 0),
        )
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.status == "confirmed")
        .where(Expense.amount_cents.is_not(None))
        .where(stat_time >= start)
        .where(stat_time < end)
        .group_by(Expense.category)
    ).all()

    pending_rows = db.execute(
        select(Expense.category, func.count(Expense.id))
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.status == "pending")
        .group_by(Expense.category)
    ).all()
    pending_by_category: dict[str, int] = {}
    for category, count in pending_rows:
        key = normalize_category(category)
        pending_by_category[key] = pending_by_category.get(key, 0) + int(count)

    aggregated: dict[str, CategorySummary] = {}
    for category, count, amount in confirmed_rows:
        key = normalize_category(category)
        existing = aggregated.get(key)
        confirmed_count = int(count)
        confirmed_amount = int(amount or 0)
        if existing is None:
            aggregated[key] = CategorySummary(
                category=key or "未分类",
                confirmed_count=confirmed_count,
                pending_count=int(pending_by_category.get(key, 0)),
                confirmed_amount_cents=confirmed_amount,
                is_uncategorized=key in UNCATEGORIZED_CATEGORIES,
            )
        else:
            aggregated[key] = CategorySummary(
                category=existing.category,
                confirmed_count=existing.confirmed_count + confirmed_count,
                pending_count=existing.pending_count,
                confirmed_amount_cents=existing.confirmed_amount_cents + confirmed_amount,
                is_uncategorized=existing.is_uncategorized,
            )
    # Categories that exist only in pending also show up.
    for key, count in pending_by_category.items():
        if key in aggregated:
            continue
        aggregated[key] = CategorySummary(
            category=key or "未分类",
            confirmed_count=0,
            pending_count=int(count),
            confirmed_amount_cents=0,
            is_uncategorized=key in UNCATEGORIZED_CATEGORIES,
        )

    summaries = sorted(
        aggregated.values(),
        key=lambda s: (s.is_uncategorized, -s.confirmed_amount_cents, s.category),
    )

    rule_count = int(
        db.scalar(
            select(func.count(CategoryRule.id))
            .where(CategoryRule.tenant_id == tenant_id)
            .where(CategoryRule.deleted_at.is_(None))
        )
        or 0
    )
    uncategorized_pending = sum(
        s.pending_count for s in summaries if s.is_uncategorized
    )
    return CategoryDashboard(
        month=month,
        summaries=summaries,
        rule_count=rule_count,
        uncategorized_pending=uncategorized_pending,
    )


def list_uncategorized_pending(db: Session, *, tenant_id: str) -> list[Expense]:
    """Return pending rows whose category is empty / 其他 / 未分类."""
    rows = db.execute(
        select(Expense)
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.status == "pending")
        .where(Expense.category.in_(UNCATEGORIZED_CATEGORIES))
        .order_by(Expense.created_at.desc())
        .limit(200)
    ).scalars().all()
    return list(rows)


def bulk_set_category(
    db: Session, *, tenant_id: str, expense_ids: list[int], category: str
) -> int:
    """Set ``category`` on the given pending rows. Returns the changed count.

    Skips any id not visible to ``tenant_id`` or not in ``pending`` status,
    instead of raising — the bulk action is best-effort and the page will
    re-render the remaining rows after the redirect.
    """
    cleaned_category = (category or "").strip()
    if not cleaned_category:
        raise AppError("invalid_request", "请选择一个分类。", status_code=400)
    if not expense_ids:
        return 0
    from app.services.expense_service import update_expense  # lazy import: expense_service imports from this module

    rows = db.execute(
        select(Expense)
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.id.in_(expense_ids))
        .where(Expense.status == "pending")
    ).scalars().all()
    changed = 0
    # ADR-0038 PR-2a / ADR-0041: 服务端 bulk 操作刚读到 row.row_version，可以直接
    # 当作 expected_row_version 喂给 update_expense（保留 PATCH 路径的原子
    # UPDATE WHERE row_version 语义，但不要求外部调用方携带 token）。
    for row in rows:
        payload = ExpenseUpdateRequest(
            category=cleaned_category,
            expected_row_version=row.row_version,
        )
        update_expense(db, row.id, tenant_id, payload)
        changed += 1
    return changed
