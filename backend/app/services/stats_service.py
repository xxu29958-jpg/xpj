from __future__ import annotations

from collections import defaultdict
import csv
from datetime import datetime, timedelta
from decimal import Decimal
from io import StringIO

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.models import Expense, ExpenseTag, Tag
from app.services.category_service import merge_categories, normalize_category
from app.services.csv_security import safe_csv_cell
from app.services.tag_service import tag_key
from app.services.time_service import (
    ensure_utc,
    local_month_bounds_utc,
    local_month_label,
    normalize_month_label,
    now_utc,
)


def _base_confirmed_query(tenant_id: str) -> Select[tuple[Expense]]:
    return (
        select(Expense)
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.status == "confirmed")
    )


def _stat_time_expr():
    return func.coalesce(Expense.expense_time, Expense.confirmed_at)


def _stat_time(expense: Expense) -> datetime | None:
    return ensure_utc(expense.expense_time) or ensure_utc(expense.confirmed_at)


def _stat_timezone(timezone_name: str | None = None) -> str:
    return (timezone_name or "").strip() or get_settings().ocr_default_timezone


def _stat_month_bounds(
    month: str, timezone_name: str | None = None
) -> tuple[datetime, datetime] | None:
    return local_month_bounds_utc(month, _stat_timezone(timezone_name))


def _clean_month_filter(month: str) -> str:
    cleaned = normalize_month_label(month)
    if cleaned is None:
        raise AppError("invalid_request", status_code=422)
    return cleaned


def _confirmed_query(
    *,
    tenant_id: str,
    month: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    timezone_name: str | None = None,
) -> Select[tuple[Expense]]:
    query = _base_confirmed_query(tenant_id)
    if category:
        query = query.where(Expense.category == normalize_category(category))
    tag_filter = tag_key(tag)
    if tag_filter:
        tagged_expense_ids = (
            select(ExpenseTag.expense_id)
            .join(Tag, Tag.id == ExpenseTag.tag_id)
            .where(ExpenseTag.tenant_id == tenant_id)
            .where(Tag.tenant_id == tenant_id)
            .where(Tag.key == tag_filter)
        )
        query = query.where(Expense.id.in_(tagged_expense_ids))
    if month:
        month = _clean_month_filter(month)
        bounds = _stat_month_bounds(month, timezone_name)
        if bounds is None:
            raise AppError("invalid_request", status_code=422)
        start_utc, end_utc = bounds
        query = query.where(_stat_time_expr() >= start_utc).where(
            _stat_time_expr() < end_utc
        )
    return query


def _confirmed_amount_query(
    *,
    tenant_id: str,
    month: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    timezone_name: str | None = None,
) -> Select[tuple[Expense]]:
    return _confirmed_query(
        tenant_id=tenant_id,
        month=month,
        category=category,
        tag=tag,
        timezone_name=timezone_name,
    ).where(Expense.amount_cents.is_not(None))


def _confirmed_ordered(query: Select[tuple[Expense]]) -> Select[tuple[Expense]]:
    return query.order_by(_stat_time_expr().desc(), Expense.id.desc())


def _filtered_confirmed(
    db: Session,
    *,
    tenant_id: str,
    month: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    timezone_name: str | None = None,
) -> list[Expense]:
    return list(
        db.scalars(
            _confirmed_ordered(
                _confirmed_query(
                    tenant_id=tenant_id,
                    month=month,
                    category=category,
                    tag=tag,
                    timezone_name=timezone_name,
                )
            )
        )
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
        if (label := local_month_label(_stat_time(expense), resolved_timezone))
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
    recent_start = now_utc() - timedelta(days=7)

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
        )
        or 0
    )

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
