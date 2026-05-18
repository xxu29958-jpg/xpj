"""Shared spending semantics for reports, budgets, goals, search, and FX.

This service is intentionally lower than feature services. It owns the
cross-surface accounting contract: statistical time, local month bounds,
category alias filtering, merchant alias matching, and FX rate dates.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.models import Expense, ExpenseTag, Tag
from app.services.merchant_alias_service import (
    canonical_merchant_for,
    enabled_merchant_alias_map,
    list_merchant_aliases,
)
from app.services.merchant_service import display_merchant, normalize_merchant
from app.services.tag_service import tag_key
from app.services.time_service import (
    ensure_utc,
    local_month_bounds_utc,
    local_month_label,
    normalize_month_label,
    parse_month_label,
    safe_zone,
)


def default_accounting_timezone_name(timezone_name: str | None = None) -> str:
    return (timezone_name or "").strip() or get_settings().ocr_default_timezone


def accounting_zone(timezone_name: str | None = None) -> ZoneInfo:
    return safe_zone(default_accounting_timezone_name(timezone_name))


def accounting_timezone_key(timezone_name: str | None = None) -> str:
    return accounting_zone(timezone_name).key


def resolve_accounting_timezone(timezone_name: str | None = None) -> tuple[str, ZoneInfo]:
    zone = accounting_zone(timezone_name)
    return zone.key, zone


def clean_month(month: str | None) -> str:
    cleaned = normalize_month_label(month)
    if cleaned is None:
        raise AppError("invalid_request", status_code=422)
    return cleaned


def parse_month(month: str | None) -> tuple[int, int]:
    parsed = parse_month_label(month)
    if parsed is None:
        raise AppError("invalid_request", status_code=422)
    return parsed


def shift_month(month: str, offset: int) -> str:
    year, month_number = parse_month(month)
    zero_based = (year * 12 + month_number - 1) + offset
    target_year = zero_based // 12
    target_month = zero_based % 12 + 1
    return f"{target_year:04d}-{target_month:02d}"


def month_labels_ending_at(month: str, count: int) -> list[str]:
    clean = clean_month(month)
    return [shift_month(clean, offset) for offset in range(-(count - 1), 1)]


def month_bounds_utc(
    month: str | None,
    timezone_name: str | None = None,
) -> tuple[datetime, datetime]:
    clean = clean_month(month)
    bounds = local_month_bounds_utc(clean, accounting_timezone_key(timezone_name))
    if bounds is None:
        raise AppError("invalid_request", status_code=422)
    return bounds


def stat_time_expr():
    return func.coalesce(Expense.expense_time, Expense.confirmed_at)


def stat_time(expense: Expense) -> datetime | None:
    return ensure_utc(expense.expense_time) or ensure_utc(expense.confirmed_at)


def stat_month_label(expense: Expense, timezone_name: str | None = None) -> str | None:
    return local_month_label(stat_time(expense), accounting_timezone_key(timezone_name))


def confirmed_query(
    *,
    tenant_id: str,
    month: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    timezone_name: str | None = None,
    amount_required: bool = False,
) -> Select[tuple[Expense]]:
    query = (
        select(Expense)
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.status == "confirmed")
    )
    if amount_required:
        query = query.where(Expense.amount_cents.is_not(None))
    if category:
        from app.services.category_service import category_filter_values

        query = query.where(Expense.category.in_(category_filter_values(category)))
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
        start_utc, end_utc = month_bounds_utc(month, timezone_name)
        time_expr = stat_time_expr()
        query = query.where(time_expr >= start_utc).where(time_expr < end_utc)
    return query


def confirmed_amount_query(
    *,
    tenant_id: str,
    month: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    timezone_name: str | None = None,
) -> Select[tuple[Expense]]:
    return confirmed_query(
        tenant_id=tenant_id,
        month=month,
        category=category,
        tag=tag,
        timezone_name=timezone_name,
        amount_required=True,
    )


def confirmed_ordered(query: Select[tuple[Expense]]) -> Select[tuple[Expense]]:
    return query.order_by(stat_time_expr().desc(), Expense.id.desc())


def filtered_confirmed(
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
            confirmed_ordered(
                confirmed_query(
                    tenant_id=tenant_id,
                    month=month,
                    category=category,
                    tag=tag,
                    timezone_name=timezone_name,
                )
            )
        )
    )


def canonical_merchant_display(merchant: str | None, alias_map: dict[str, str]) -> str:
    display = display_merchant(merchant)
    if not display:
        return "未填写商家"
    canonical = display_merchant(canonical_merchant_for(display, alias_map=alias_map))
    return canonical or display


def enabled_merchant_display_map(db: Session, *, tenant_id: str) -> dict[str, str]:
    return enabled_merchant_alias_map(db, tenant_id=tenant_id)


def merchant_search_terms(db: Session, *, tenant_id: str, term: str) -> list[str]:
    terms = {term}
    needle = term.casefold()
    normalized = normalize_merchant(term)
    for alias in list_merchant_aliases(db, tenant_id):
        if not alias.enabled:
            continue
        alias_values = {
            alias.alias,
            alias.alias_key,
            alias.canonical_merchant,
            alias.canonical_key,
        }
        alias_values_folded = {value.casefold() for value in alias_values if value}
        if (
            any(needle in value for value in alias_values_folded)
            or normalized in {alias.alias_key, alias.canonical_key}
        ):
            terms.add(alias.alias)
            terms.add(alias.canonical_merchant)
    return sorted(term for term in terms if term)


def fx_rate_date_for_expense_time(
    expense_time: datetime | None = None,
    timezone_name: str | None = None,
) -> date:
    zone = accounting_zone(timezone_name)
    if expense_time is None:
        return datetime.now(UTC).astimezone(zone).date()
    if expense_time.tzinfo is None or expense_time.utcoffset() is None:
        return expense_time.replace(tzinfo=zone).date()
    if expense_time.utcoffset() == UTC.utcoffset(expense_time):
        return expense_time.astimezone(zone).date()
    return expense_time.date()
