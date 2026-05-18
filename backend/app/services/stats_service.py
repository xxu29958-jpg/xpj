from __future__ import annotations

from collections import defaultdict
import csv
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Expense, ExpenseTag, Tag
from app.services.category_service import merge_categories, normalize_category
from app.services.csv_security import safe_csv_cell
from app.services.spending_contract_service import (
    clean_month as _contract_clean_month,
    confirmed_amount_query as _contract_confirmed_amount_query,
    confirmed_ordered as _contract_confirmed_ordered,
    confirmed_query as _contract_confirmed_query,
    default_accounting_timezone_name,
    filtered_confirmed as _contract_filtered_confirmed,
    month_bounds_utc,
    stat_month_label,
    stat_time as _contract_stat_time,
    stat_time_expr as _contract_stat_time_expr,
)
from app.services.time_service import (
    ensure_utc,
    now_utc,
)


def _base_confirmed_query(tenant_id: str) -> Select[tuple[Expense]]:
    return _contract_confirmed_query(tenant_id=tenant_id)


def _stat_time_expr():
    return _contract_stat_time_expr()


def _stat_time(expense: Expense):
    return _contract_stat_time(expense)


def _stat_timezone(timezone_name: str | None = None) -> str:
    return default_accounting_timezone_name(timezone_name)


def _stat_month_bounds(
    month: str, timezone_name: str | None = None
):
    return month_bounds_utc(month, timezone_name)


def _clean_month_filter(month: str) -> str:
    return _contract_clean_month(month)


def _confirmed_query(
    *,
    tenant_id: str,
    month: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    timezone_name: str | None = None,
) -> Select[tuple[Expense]]:
    return _contract_confirmed_query(
        tenant_id=tenant_id,
        month=month,
        category=category,
        tag=tag,
        timezone_name=timezone_name,
    )


def _confirmed_amount_query(
    *,
    tenant_id: str,
    month: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    timezone_name: str | None = None,
) -> Select[tuple[Expense]]:
    return _contract_confirmed_amount_query(
        tenant_id=tenant_id,
        month=month,
        category=category,
        tag=tag,
        timezone_name=timezone_name,
    )


def _confirmed_ordered(query: Select[tuple[Expense]]) -> Select[tuple[Expense]]:
    return _contract_confirmed_ordered(query)


def _filtered_confirmed(
    db: Session,
    *,
    tenant_id: str,
    month: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    timezone_name: str | None = None,
) -> list[Expense]:
    return _contract_filtered_confirmed(
        db,
        tenant_id=tenant_id,
        month=month,
        category=category,
        tag=tag,
        timezone_name=timezone_name,
    )


def list_categories(db: Session, tenant_id: str) -> list[str]:
    return merge_categories(
        list(
            db.scalars(
                select(Expense.category)
                .where(Expense.tenant_id == tenant_id)
                .distinct()
            )
        )
    )


def list_months(
    db: Session, tenant_id: str, timezone_name: str | None = None
) -> list[str]:
    resolved_timezone = _stat_timezone(timezone_name)
    expenses = db.scalars(
        select(Expense)
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.status == "confirmed")
        .where(_stat_time_expr().is_not(None))
    )
    months = {
        label
        for expense in expenses
        if (label := stat_month_label(expense, resolved_timezone))
        is not None
    }
    return sorted(months, reverse=True)


def export_confirmed_csv(
    db: Session,
    *,
    tenant_id: str,
    month: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    timezone_name: str | None = None,
) -> str:
    expenses = _filtered_confirmed(
        db,
        tenant_id=tenant_id,
        month=month,
        category=category,
        tag=tag,
        timezone_name=timezone_name,
    )
    output = StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        [
            "id",
            "public_id",
            "amount_cents",
            "amount_yuan",
            "original_currency_code",
            "original_amount_minor",
            "exchange_rate_to_cny",
            "exchange_rate_date",
            "exchange_rate_source",
            "merchant",
            "category",
            "note",
            "source",
            "expense_time",
            "confirmed_at",
            "tags",
            "value_score",
            "regret_score",
        ]
    )
    for expense in expenses:
        if expense.amount_cents is None:
            amount_cents: int | str = ""
            amount_yuan = ""
        else:
            amount_cents = int(expense.amount_cents)
            amount_yuan = str((Decimal(amount_cents) / Decimal(100)).quantize(Decimal("0.01")))
        stat_time = _stat_time(expense)
        confirmed_at = ensure_utc(expense.confirmed_at)
        writer.writerow(
            [
                expense.id,
                expense.public_id,
                amount_cents,
                amount_yuan,
                expense.original_currency_code,
                expense.original_amount_minor if expense.original_amount_minor is not None else "",
                expense.exchange_rate_to_cny if expense.exchange_rate_to_cny is not None else "",
                expense.exchange_rate_date.isoformat() if expense.exchange_rate_date else "",
                safe_csv_cell(expense.exchange_rate_source or ""),
                safe_csv_cell(expense.merchant or ""),
                safe_csv_cell(expense.category),
                safe_csv_cell(expense.note or ""),
                safe_csv_cell(expense.source),
                stat_time.isoformat().replace("+00:00", "Z") if stat_time else "",
                confirmed_at.isoformat().replace("+00:00", "Z") if confirmed_at else "",
                safe_csv_cell(expense.tags or ""),
                expense.value_score or "",
                expense.regret_score or "",
            ]
        )
    return output.getvalue()


def _tag_stats_for_filtered_query(db: Session, tenant_id: str, filtered) -> list[dict]:
    rows = db.execute(
        select(
            Tag.name,
            func.coalesce(func.sum(filtered.c.amount_cents), 0),
            func.count(filtered.c.id),
        )
        .select_from(filtered)
        .join(
            ExpenseTag,
            (ExpenseTag.expense_id == filtered.c.id)
            & (ExpenseTag.tenant_id == tenant_id),
        )
        .join(Tag, (Tag.id == ExpenseTag.tag_id) & (Tag.tenant_id == tenant_id))
        .group_by(Tag.name)
    )
    stats = [
        {"tag": str(tag), "amount_cents": int(amount or 0), "count": int(count or 0)}
        for tag, amount, count in rows
    ]
    return sorted(stats, key=lambda item: int(item["amount_cents"]), reverse=True)


def monthly_stats(
    db: Session,
    month: str,
    tenant_id: str,
    timezone_name: str | None = None,
    tag: str | None = None,
) -> dict:
    by_category: dict[str, dict[str, int | str]] = defaultdict(
        lambda: {"category": "", "amount_cents": 0, "count": 0}
    )

    month = _clean_month_filter(month)
    total_amount_cents = 0
    total_count = 0
    bounds = _stat_month_bounds(month, timezone_name)
    if bounds is None:
        raise AppError("invalid_request", status_code=422)
    filtered = _confirmed_amount_query(
        tenant_id=tenant_id,
        month=month,
        tag=tag,
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
    for category_value, amount_value, count_value in rows:
        amount = int(amount_value or 0)
        count = int(count_value or 0)
        total_amount_cents += amount
        total_count += count
        category = normalize_category(category_value)
        bucket = by_category[category]
        bucket["category"] = category
        bucket["amount_cents"] = int(bucket["amount_cents"]) + amount
        bucket["count"] = int(bucket["count"]) + count

    return {
        "month": month,
        "total_amount_cents": total_amount_cents,
        "count": total_count,
        "by_category": sorted(
            by_category.values(),
            key=lambda item: int(item["amount_cents"]),
            reverse=True,
        ),
        "by_tag": _tag_stats_for_filtered_query(db, tenant_id, filtered),
    }


def lifestyle_stats(
    db: Session, month: str, tenant_id: str, timezone_name: str | None = None
) -> dict:
    month = _clean_month_filter(month)
    month_expenses = list(
        db.scalars(
            _confirmed_query(
                tenant_id=tenant_id, month=month, timezone_name=timezone_name
            ).where(Expense.amount_cents.is_not(None))
        )
    )
    bounds = _stat_month_bounds(month, timezone_name)
    if bounds is None:
        raise AppError("invalid_request", status_code=422)
    month_start, month_end = bounds
    recent_end = min(now_utc(), month_end)
    recent_start = max(month_start, recent_end - timedelta(days=7))

    ai_subscription_amount_cents = sum(
        item.amount_cents or 0
        for item in month_expenses
        if normalize_category(item.category) == "AI订阅"
    )
    digital_amount_cents = sum(
        item.amount_cents or 0
        for item in month_expenses
        if normalize_category(item.category) == "数码"
    )
    max_expense = max(
        month_expenses, key=lambda item: item.amount_cents or 0, default=None
    )
    recent_7_days_amount_cents = int(
        db.scalar(
            select(func.coalesce(func.sum(Expense.amount_cents), 0))
            .where(Expense.tenant_id == tenant_id)
            .where(Expense.status == "confirmed")
            .where(Expense.amount_cents.is_not(None))
            .where(_stat_time_expr() >= recent_start)
            .where(_stat_time_expr() < recent_end)
        )
        or 0
    ) if recent_start < recent_end else 0

    merchant_counts: dict[str, int] = defaultdict(int)
    for item in month_expenses:
        merchant = (item.merchant or "").strip()
        if merchant:
            merchant_counts[merchant] += 1

    frequent_merchants = [
        {"merchant": merchant, "count": count}
        for merchant, count in sorted(
            merchant_counts.items(), key=lambda pair: (-pair[1], pair[0])
        )[:5]
    ]

    return {
        "month": month,
        "ai_subscription_amount_cents": ai_subscription_amount_cents,
        "digital_amount_cents": digital_amount_cents,
        "max_expense": max_expense,
        "recent_7_days_amount_cents": recent_7_days_amount_cents,
        "frequent_merchants": frequent_merchants,
    }
