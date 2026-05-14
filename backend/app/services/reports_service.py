from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.models import Expense
from app.services.category_service import normalize_category
from app.services.merchant_alias_service import canonical_merchant_for, enabled_merchant_alias_map
from app.services.merchant_service import display_merchant, normalize_merchant
from app.services.time_service import local_month_bounds_utc, safe_zone

ReportGranularity = Literal["day", "week", "month"]


def _stat_time_expr():
    return func.coalesce(Expense.expense_time, Expense.confirmed_at)


def _resolve_timezone(timezone_name: str | None) -> tuple[str, ZoneInfo]:
    requested = (timezone_name or "").strip() or get_settings().ocr_default_timezone
    zone = safe_zone(requested)
    return zone.key, zone


def _parse_month(month: str) -> tuple[int, int]:
    try:
        year_text, month_text = month.split("-", 1)
        year = int(year_text)
        month_number = int(month_text)
    except (AttributeError, ValueError) as exc:
        raise AppError("invalid_request", status_code=422) from exc
    if not 1 <= month_number <= 12:
        raise AppError("invalid_request", status_code=422)
    return year, month_number


def _shift_month(month: str, offset: int) -> str:
    year, month_number = _parse_month(month)
    zero_based = (year * 12 + month_number - 1) + offset
    target_year = zero_based // 12
    target_month = zero_based % 12 + 1
    return f"{target_year:04d}-{target_month:02d}"


def _month_labels_ending_at(month: str, count: int) -> list[str]:
    return [_shift_month(month, offset) for offset in range(-(count - 1), 1)]


def _days_in_month(month: str, zone: ZoneInfo) -> list[date]:
    bounds = local_month_bounds_utc(month, zone.key)
    if bounds is None:
        raise AppError("invalid_request", status_code=422)
    start_utc, end_utc = bounds
    cursor = start_utc.astimezone(zone).date()
    end_date = end_utc.astimezone(zone).date()
    days: list[date] = []
    while cursor < end_date:
        days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _local_day_bounds_utc(day: date, zone: ZoneInfo) -> tuple[datetime, datetime]:
    start_local = datetime(day.year, day.month, day.day, tzinfo=zone)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def _local_date_range_bounds_utc(
    start_day: date,
    end_day_exclusive: date,
    zone: ZoneInfo,
) -> tuple[datetime, datetime]:
    start_local = datetime(start_day.year, start_day.month, start_day.day, tzinfo=zone)
    end_local = datetime(
        end_day_exclusive.year,
        end_day_exclusive.month,
        end_day_exclusive.day,
        tzinfo=zone,
    )
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def _filter_range(query, *, tenant_id: str, start_utc: datetime, end_utc: datetime):
    stat_time = _stat_time_expr()
    return (
        query.where(Expense.tenant_id == tenant_id)
        .where(Expense.status == "confirmed")
        .where(stat_time >= start_utc)
        .where(stat_time < end_utc)
    )


def _range_amount_count(
    db: Session,
    *,
    tenant_id: str,
    start_utc: datetime,
    end_utc: datetime,
) -> tuple[int, int]:
    row = db.execute(
        _filter_range(
            select(
                func.coalesce(func.sum(Expense.amount_cents), 0),
                func.count(Expense.id),
            ),
            tenant_id=tenant_id,
            start_utc=start_utc,
            end_utc=end_utc,
        )
    ).one()
    return int(row[0] or 0), int(row[1] or 0)


def _month_bounds(month: str, timezone_name: str) -> tuple[datetime, datetime]:
    bounds = local_month_bounds_utc(month, timezone_name)
    if bounds is None:
        raise AppError("invalid_request", status_code=422)
    return bounds


def _trend_points(
    db: Session,
    *,
    tenant_id: str,
    month: str,
    granularity: ReportGranularity,
    timezone_name: str,
    zone: ZoneInfo,
) -> list[dict]:
    if granularity == "month":
        points: list[dict] = []
        for label in _month_labels_ending_at(month, 6):
            start_utc, end_utc = _month_bounds(label, timezone_name)
            amount, count = _range_amount_count(
                db,
                tenant_id=tenant_id,
                start_utc=start_utc,
                end_utc=end_utc,
            )
            points.append(
                {
                    "bucket": label,
                    "label": label,
                    "amount_cents": amount,
                    "count": count,
                }
            )
        return points

    days = _days_in_month(month, zone)
    if granularity == "week":
        month_start = days[0]
        month_end_exclusive = days[-1] + timedelta(days=1)
        week_starts = sorted({day - timedelta(days=day.weekday()) for day in days})
        points = []
        for week_start in week_starts:
            week_end_exclusive = week_start + timedelta(days=7)
            start_day = max(week_start, month_start)
            end_day = min(week_end_exclusive, month_end_exclusive)
            start_utc, end_utc = _local_date_range_bounds_utc(start_day, end_day, zone)
            amount, count = _range_amount_count(
                db,
                tenant_id=tenant_id,
                start_utc=start_utc,
                end_utc=end_utc,
            )
            label_end = end_day - timedelta(days=1)
            points.append(
                {
                    "bucket": week_start.isoformat(),
                    "label": f"{start_day.strftime('%m-%d')}~{label_end.strftime('%m-%d')}",
                    "amount_cents": amount,
                    "count": count,
                }
            )
        return points

    points = []
    for day in days:
        start_utc, end_utc = _local_day_bounds_utc(day, zone)
        amount, count = _range_amount_count(
            db,
            tenant_id=tenant_id,
            start_utc=start_utc,
            end_utc=end_utc,
        )
        points.append(
            {
                "bucket": day.isoformat(),
                "label": day.strftime("%m-%d"),
                "amount_cents": amount,
                "count": count,
            }
        )
    return points


def _canonical_display(merchant: str, alias_map: dict[str, str]) -> str:
    display = display_merchant(merchant)
    if not display:
        return "未填写商家"
    canonical = display_merchant(canonical_merchant_for(display, alias_map=alias_map))
    return canonical or display


def _merchant_ranking(
    db: Session,
    *,
    tenant_id: str,
    start_utc: datetime,
    end_utc: datetime,
    top_n: int,
) -> list[dict]:
    rows = db.execute(
        _filter_range(
            select(
                func.coalesce(Expense.merchant, ""),
                func.coalesce(func.sum(Expense.amount_cents), 0),
                func.count(Expense.id),
            ).group_by(func.coalesce(Expense.merchant, "")),
            tenant_id=tenant_id,
            start_utc=start_utc,
            end_utc=end_utc,
        )
    )
    alias_map = enabled_merchant_alias_map(db, tenant_id=tenant_id)
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
    return sorted(
        buckets.values(),
        key=lambda item: (-int(item["amount_cents"]), -int(item["count"]), str(item["merchant"])),
    )[:top_n]


def _category_totals(
    db: Session,
    *,
    tenant_id: str,
    start_utc: datetime,
    end_utc: datetime,
) -> dict[str, dict[str, int | str]]:
    rows = db.execute(
        _filter_range(
            select(
                Expense.category,
                func.coalesce(func.sum(Expense.amount_cents), 0),
                func.count(Expense.id),
            ).group_by(Expense.category),
            tenant_id=tenant_id,
            start_utc=start_utc,
            end_utc=end_utc,
        )
    )
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
    items: list[dict] = []
    for category in set(current) | set(previous):
        current_item = current.get(category, {"amount_cents": 0, "count": 0})
        previous_item = previous.get(category, {"amount_cents": 0, "count": 0})
        amount = int(current_item["amount_cents"])
        prev_amount = int(previous_item["amount_cents"])
        count = int(current_item["count"])
        prev_count = int(previous_item["count"])
        items.append(
            {
                "category": category,
                "amount_cents": amount,
                "count": count,
                "previous_amount_cents": prev_amount,
                "previous_count": prev_count,
                "delta_amount_cents": amount - prev_amount,
                "delta_count": count - prev_count,
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


def reports_overview(
    db: Session,
    *,
    month: str,
    tenant_id: str,
    timezone_name: str | None = None,
    granularity: ReportGranularity = "day",
    top_n: int = 8,
) -> dict:
    _parse_month(month)
    timezone_key, zone = _resolve_timezone(timezone_name)
    current_start_utc, current_end_utc = _month_bounds(month, timezone_key)
    previous_month = _shift_month(month, -1)
    previous_start_utc, previous_end_utc = _month_bounds(previous_month, timezone_key)
    total_amount, count = _range_amount_count(
        db,
        tenant_id=tenant_id,
        start_utc=current_start_utc,
        end_utc=current_end_utc,
    )
    previous_total, previous_count = _range_amount_count(
        db,
        tenant_id=tenant_id,
        start_utc=previous_start_utc,
        end_utc=previous_end_utc,
    )
    return {
        "month": month,
        "timezone": timezone_key,
        "granularity": granularity,
        "total_amount_cents": total_amount,
        "count": count,
        "previous_month": previous_month,
        "previous_total_amount_cents": previous_total,
        "previous_count": previous_count,
        "trend": _trend_points(
            db,
            tenant_id=tenant_id,
            month=month,
            granularity=granularity,
            timezone_name=timezone_key,
            zone=zone,
        ),
        "merchant_ranking": _merchant_ranking(
            db,
            tenant_id=tenant_id,
            start_utc=current_start_utc,
            end_utc=current_end_utc,
            top_n=top_n,
        ),
        "category_comparison": _category_comparison(
            db,
            tenant_id=tenant_id,
            current_start_utc=current_start_utc,
            current_end_utc=current_end_utc,
            previous_start_utc=previous_start_utc,
            previous_end_utc=previous_end_utc,
        ),
    }
