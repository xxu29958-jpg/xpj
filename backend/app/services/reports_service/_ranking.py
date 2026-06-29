"""Merchant ranking + category totals/comparison."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ledger_scope import add_ledger_scope
from app.models import Expense
from app.services.category_service import category_filter_values, normalize_category
from app.services.merchant_alias_service import canonical_merchant_for
from app.services.merchant_service import display_merchant, normalize_merchant
from app.services.reports_service._models import ReportRankingMetric
from app.services.reports_service._time import _stat_time_expr
from app.services.spending_contract_service import enabled_merchant_display_map


def _canonical_display(merchant: str, alias_map: dict[str, str]) -> str:
    display = display_merchant(merchant)
    if not display:
        return "未填写商家"
    canonical = display_merchant(canonical_merchant_for(display, alias_map=alias_map))
    return canonical or display


def _category_filter_values(category: str | None) -> set[str]:
    return category_filter_values(category)


def _merchant_ranking(
    db: Session,
    *,
    tenant_id: str,
    start_utc: datetime,
    end_utc: datetime,
    top_n: int,
    category: str | None,
    ranking_metric: ReportRankingMetric,
) -> list[dict]:
    stat_time = _stat_time_expr()
    # Reuse one expression object in both SELECT and GROUP BY. Rebuilding
    # ``func.coalesce(Expense.merchant, "")`` twice binds the "" literal as two
    # different parameters, so PostgreSQL sees coalesce(merchant,$1) vs
    # coalesce(merchant,$2) and rejects the SELECT column as not grouped
    # (SQLite is lenient and never complained) — ADR-0041.
    merchant_key = func.coalesce(Expense.merchant, "")
    statement = (
        add_ledger_scope(
            select(
                merchant_key,
                func.coalesce(func.sum(Expense.amount_cents), 0),
                func.count(Expense.id),
            ).group_by(merchant_key),
            Expense,
            tenant_id,
        )
        .where(Expense.status == "confirmed")
        .where(Expense.amount_cents.is_not(None))
        .where(stat_time >= start_utc)
        .where(stat_time < end_utc)
    )
    if category:
        statement = statement.where(
            Expense.category.in_(_category_filter_values(category))
        )
    rows = db.execute(statement)
    alias_map = enabled_merchant_display_map(db, tenant_id=tenant_id)
    buckets: dict[str, dict[str, int | str]] = defaultdict(
        lambda: {"merchant": "", "amount_cents": 0, "count": 0}
    )
    for merchant_raw, amount_value, count_value in rows:
        display = _canonical_display(str(merchant_raw or ""), alias_map)
        key = normalize_merchant(display) or "__empty_merchant__"
        bucket = buckets[key]
        bucket["merchant"] = display
        bucket["amount_cents"] = int(bucket["amount_cents"]) + int(amount_value or 0)
        bucket["count"] = int(bucket["count"]) + int(count_value or 0)
    if ranking_metric == "count":
        return sorted(
            buckets.values(),
            key=lambda item: (
                -int(item["count"]),
                -int(item["amount_cents"]),
                str(item["merchant"]),
            ),
        )[:top_n]
    return sorted(
        buckets.values(),
        key=lambda item: (
            -int(item["amount_cents"]),
            -int(item["count"]),
            str(item["merchant"]),
        ),
    )[:top_n]


def _category_totals(
    db: Session,
    *,
    tenant_id: str,
    start_utc: datetime,
    end_utc: datetime,
) -> dict[str, dict[str, int | str]]:
    stat_time = _stat_time_expr()
    statement = (
        add_ledger_scope(
            select(
                Expense.category,
                func.coalesce(func.sum(Expense.amount_cents), 0),
                func.count(Expense.id),
            ).group_by(Expense.category),
            Expense,
            tenant_id,
        )
        .where(Expense.status == "confirmed")
        .where(Expense.amount_cents.is_not(None))
        .where(stat_time >= start_utc)
        .where(stat_time < end_utc)
    )
    rows = db.execute(statement)
    buckets: dict[str, dict[str, int | str]] = defaultdict(
        lambda: {"category": "", "amount_cents": 0, "count": 0}
    )
    for category_raw, amount_value, count_value in rows:
        category = normalize_category(category_raw)
        bucket = buckets[category]
        bucket["category"] = category
        bucket["amount_cents"] = int(bucket["amount_cents"]) + int(amount_value or 0)
        bucket["count"] = int(bucket["count"]) + int(count_value or 0)
    return buckets


def _category_comparison(
    db: Session,
    *,
    tenant_id: str,
    current_start_utc: datetime,
    current_end_utc: datetime,
    previous_start_utc: datetime,
    previous_end_utc: datetime,
    year_over_year_start_utc: datetime,
    year_over_year_end_utc: datetime,
) -> list[dict]:
    current = _category_totals(
        db,
        tenant_id=tenant_id,
        start_utc=current_start_utc,
        end_utc=current_end_utc,
    )
    previous = _category_totals(
        db,
        tenant_id=tenant_id,
        start_utc=previous_start_utc,
        end_utc=previous_end_utc,
    )
    year_over_year = _category_totals(
        db,
        tenant_id=tenant_id,
        start_utc=year_over_year_start_utc,
        end_utc=year_over_year_end_utc,
    )
    items: list[dict] = []
    for category in set(current) | set(previous) | set(year_over_year):
        current_item = current.get(category, {"amount_cents": 0, "count": 0})
        previous_item = previous.get(category, {"amount_cents": 0, "count": 0})
        yoy_item = year_over_year.get(category, {"amount_cents": 0, "count": 0})
        amount = int(current_item["amount_cents"])
        prev_amount = int(previous_item["amount_cents"])
        yoy_amount = int(yoy_item["amount_cents"])
        count = int(current_item["count"])
        prev_count = int(previous_item["count"])
        yoy_count = int(yoy_item["count"])
        items.append(
            {
                "category": category,
                "amount_cents": amount,
                "count": count,
                "previous_amount_cents": prev_amount,
                "previous_count": prev_count,
                "delta_amount_cents": amount - prev_amount,
                "delta_count": count - prev_count,
                "year_over_year_amount_cents": yoy_amount,
                "year_over_year_count": yoy_count,
                "year_over_year_delta_amount_cents": amount - yoy_amount,
                "year_over_year_delta_count": count - yoy_count,
            }
        )
    return sorted(
        items,
        key=lambda item: (
            -int(item["amount_cents"]),
            -int(item["previous_amount_cents"]),
            str(item["category"]),
        ),
    )
