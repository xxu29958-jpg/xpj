from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime, timedelta
from io import StringIO

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Expense, ExpenseTag, Tag
from app.money_contract import projection_sum_to_int
from app.services.category_service import list_ledger_category_options, normalize_category
from app.services.csv_security import safe_csv_cell
from app.services.expense_service import filtered_confirmed_stream
from app.services.spending_contract_service import (
    accounting_zone,
    canonical_merchant_display,
    confirmed_stream_query,
    current_accounting_month,
    default_accounting_timezone_name,
    enabled_merchant_display_map,
    month_bounds_utc,
)
from app.services.spending_contract_service import (
    clean_month as _contract_clean_month,
)
from app.services.spending_contract_service import (
    confirmed_query as _contract_confirmed_query,
)
from app.services.spending_contract_service import (
    stat_time as _contract_stat_time,
)
from app.services.stats_money import (
    export_money_fields as _export_money_fields,
)
from app.services.time_service import (
    ensure_utc,
    now_utc,
)


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


def list_categories(db: Session, tenant_id: str) -> list[str]:
    return list_ledger_category_options(db, tenant_id=tenant_id)


def list_months(
    db: Session, tenant_id: str, timezone_name: str | None = None
) -> list[str]:
    resolved_timezone = _stat_timezone(timezone_name)
    current_month_label = current_accounting_month(resolved_timezone)
    stream = confirmed_stream_query(
        tenant_id=tenant_id,
        timezone_name=resolved_timezone,
    )
    months = {
        stream_date.strftime("%Y-%m")
        for stream_date in db.scalars(
            select(stream.c.stream_date).where(stream.c.stream_date.is_not(None))
        )
        if stream_date.strftime("%Y-%m") <= current_month_label
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
    entries = filtered_confirmed_stream(
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
            # Append-only currency-aware replacements.  Keep every released
            # column above in its original position for positional consumers.
            "home_currency_code",
            "amount_home_major",
            "entry_kind",
            "offset_kind",
            "root_expense_id",
            "root_expense_public_id",
            "stream_date",
            "stream_amount_cents",
            "lineage_status",
            "lineage_home_net_cents",
        ]
    )
    for entry in entries:
        writer.writerow(_confirmed_stream_csv_row(entry))
    return output.getvalue()


def _confirmed_stream_csv_row(entry) -> list:
    root = entry.root
    if entry.entry_kind == "expense":
        amount_cents, amount_yuan, amount_home_major = _export_money_fields(root)
        stat_time = _stat_time(root)
        confirmed_at = ensure_utc(root.confirmed_at)
        return [
            root.id,
            root.public_id,
            amount_cents,
            amount_yuan,
            root.original_currency_code,
            root.original_amount_minor if root.original_amount_minor is not None else "",
            root.exchange_rate_to_cny if root.exchange_rate_to_cny is not None else "",
            root.exchange_rate_date.isoformat() if root.exchange_rate_date else "",
            safe_csv_cell(root.exchange_rate_source or ""),
            safe_csv_cell(root.merchant or ""),
            safe_csv_cell(root.category),
            safe_csv_cell(root.note or ""),
            safe_csv_cell(root.source),
            stat_time.isoformat().replace("+00:00", "Z") if stat_time else "",
            confirmed_at.isoformat().replace("+00:00", "Z") if confirmed_at else "",
            safe_csv_cell(root.tags or ""),
            root.value_score or "",
            root.regret_score or "",
            root.home_currency_code,
            amount_home_major,
            entry.entry_kind,
            "",
            root.id,
            root.public_id,
            entry.stream_date.isoformat(),
            entry.stream_amount_cents,
            entry.lineage_status,
            entry.lineage_home_net_cents,
        ]
    offset = entry.offset
    if offset is None:
        raise ValueError("offset CSV row requires an offset projection")
    amount_cents, amount_yuan, amount_home_major = _export_money_fields(offset)
    return [
        "",
        offset.public_id,
        amount_cents,
        amount_yuan,
        offset.original_currency_code,
        offset.original_amount_minor,
        "",
        "",
        "",
        safe_csv_cell(root.merchant or ""),
        safe_csv_cell(offset.category),
        "",
        "",
        entry.stream_date.isoformat(),
        "",
        "",
        "",
        "",
        offset.home_currency_code,
        amount_home_major,
        entry.entry_kind,
        offset.kind,
        root.id,
        root.public_id,
        entry.stream_date.isoformat(),
        entry.stream_amount_cents,
        entry.lineage_status,
        entry.lineage_home_net_cents,
    ]


def _tag_stats_for_filtered_query(db: Session, tenant_id: str, filtered) -> list[dict]:
    rows = db.execute(
        select(
            Tag.name,
            func.coalesce(func.sum(filtered.c.stream_amount_cents), 0),
            func.count(filtered.c.entry_id),
        )
        .select_from(filtered)
        .join(
            ExpenseTag,
            (ExpenseTag.expense_id == filtered.c.root_expense_id)
            & (ExpenseTag.tenant_id == tenant_id),
        )
        .join(Tag, (Tag.id == ExpenseTag.tag_id) & (Tag.tenant_id == tenant_id))
        .where(Tag.deleted_at.is_(None))  # ADR-0043: exclude soft-deleted tags
        .group_by(Tag.name)
    )
    stats = [
        {
            "tag": str(tag),
            "amount_cents": projection_sum_to_int(
                amount,
                label="stats.tag_amount",
                empty_is_zero=True,
            ),
            "count": int(count or 0),
        }
        for tag, amount, count in rows
    ]
    return sorted(stats, key=lambda item: int(item["amount_cents"]), reverse=True)


def top_expenses_for_month(
    db: Session,
    *,
    tenant_id: str,
    month: str | None = None,
    tag: str | None = None,
    timezone_name: str | None = None,
    limit: int = 5,
) -> list[Expense]:
    """Highest-amount confirmed expenses for the period (ledger-scoped).

    Used by the /web/reports 大额支出 panel (moved from the retired /web/stats
    page in UI/UX 批 14). Skips rows with NULL amount_cents.
    """
    return list(
        db.scalars(
            _confirmed_query(
                tenant_id=tenant_id,
                month=month,
                tag=tag,
                timezone_name=timezone_name,
            )
            .where(Expense.amount_cents.is_not(None))
            .order_by(Expense.amount_cents.desc())
            .limit(limit)
        )
    )


def _ranked_scored_expenses(
    expenses: list[Expense],
    *,
    score_attr: str,
    limit: int = 5,
) -> list[Expense]:
    def sort_key(expense: Expense) -> tuple[int, int, float, int]:
        stat_time = _stat_time(expense)
        timestamp = stat_time.timestamp() if stat_time is not None else 0.0
        return (
            -(getattr(expense, score_attr) or 0),
            -projection_sum_to_int(
                expense.amount_cents,
                label="stats.ranked_expense",
                empty_is_zero=True,
            ),
            -timestamp,
            -(expense.id or 0),
        )

    scored = [item for item in expenses if getattr(item, score_attr) is not None]
    return sorted(scored, key=sort_key)[:limit]


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
    filtered = confirmed_stream_query(
        tenant_id=tenant_id,
        month=month,
        tag=tag,
        timezone_name=timezone_name,
        amount_required=True,
    )
    rows = db.execute(
        select(
            filtered.c.category,
            func.coalesce(func.sum(filtered.c.stream_amount_cents), 0),
            func.count(filtered.c.entry_id),
        )
        .select_from(filtered)
        .group_by(filtered.c.category)
    )
    for category_value, amount_value, count_value in rows:
        amount = projection_sum_to_int(
            amount_value,
            label="stats.category_row",
            empty_is_zero=True,
        )
        count = int(count_value or 0)
        total_amount_cents = projection_sum_to_int(
            total_amount_cents + amount,
            label="stats.month_total",
        )
        total_count += count
        category = normalize_category(category_value)
        bucket = by_category[category]
        bucket["category"] = category
        bucket["amount_cents"] = projection_sum_to_int(
            projection_sum_to_int(
                bucket["amount_cents"],
                label="stats.category_bucket",
            )
            + amount,
            label="stats.normalized_category_total",
        )
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


def _lifestyle_stream_totals(
    db: Session,
    *,
    tenant_id: str,
    month: str,
    timezone_name: str | None,
    recent_start: datetime,
    recent_end: datetime,
) -> tuple[dict[str, int], list[dict], int]:
    stream = confirmed_stream_query(
        tenant_id=tenant_id,
        month=month,
        timezone_name=timezone_name,
        amount_required=True,
    )
    alias_map = enabled_merchant_display_map(db, tenant_id=tenant_id)
    category_amounts: dict[str, int] = defaultdict(int)
    merchant_counts: dict[str, int] = defaultdict(int)
    merchant_amounts: dict[str, int] = defaultdict(int)
    recent_7_days_amount_cents = 0
    zone = accounting_zone(timezone_name)
    recent_start_date = recent_start.astimezone(zone).date()
    recent_end_date = recent_end.astimezone(zone).date()
    for category_raw, merchant_raw, stream_date, stream_amount in db.execute(
        select(
            stream.c.category,
            stream.c.merchant,
            stream.c.stream_date,
            stream.c.stream_amount_cents,
        )
    ):
        amount = projection_sum_to_int(stream_amount, label="stats.lifestyle_entry")
        category = normalize_category(category_raw)
        category_amounts[category] = projection_sum_to_int(
            category_amounts[category] + amount,
            label="stats.lifestyle_category",
        )
        if merchant_raw and merchant_raw.strip():
            merchant = canonical_merchant_display(merchant_raw, alias_map)
            merchant_counts[merchant] += 1
            merchant_amounts[merchant] = projection_sum_to_int(
                merchant_amounts[merchant] + amount,
                label="stats.lifestyle_merchant",
            )
        if recent_start < recent_end and recent_start_date <= stream_date <= recent_end_date:
            recent_7_days_amount_cents = projection_sum_to_int(
                recent_7_days_amount_cents + amount,
                label="stats.recent_seven_days",
            )
    frequent_merchants = [
        {
            "merchant": merchant,
            "count": count,
            "amount_cents": merchant_amounts[merchant],
        }
        for merchant, count in sorted(
            merchant_counts.items(),
            key=lambda pair: (-merchant_amounts[pair[0]], -pair[1], pair[0]),
        )[:5]
    ]
    return category_amounts, frequent_merchants, recent_7_days_amount_cents


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
    category_amounts, frequent_merchants, recent_amount = _lifestyle_stream_totals(
        db,
        tenant_id=tenant_id,
        month=month,
        timezone_name=timezone_name,
        recent_start=recent_start,
        recent_end=recent_end,
    )
    max_expense = max(
        month_expenses, key=lambda item: item.amount_cents or 0, default=None
    )

    return {
        "month": month,
        "ai_subscription_amount_cents": category_amounts.get("AI订阅", 0),
        "digital_amount_cents": category_amounts.get("数码", 0),
        "max_expense": max_expense,
        "recent_7_days_amount_cents": recent_amount,
        "frequent_merchants": frequent_merchants,
        "best_value_expenses": _ranked_scored_expenses(
            month_expenses, score_attr="value_score"
        ),
        "most_regretted_expenses": _ranked_scored_expenses(
            month_expenses, score_attr="regret_score"
        ),
    }
