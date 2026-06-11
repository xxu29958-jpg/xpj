"""DB-level statistics queries used by the /web surface.

These functions were previously private helpers inside
``app/routes/web_common.py``. They were doing direct ORM queries in the route
layer, which violates the routes → services → models layering. Extracting
them keeps ``web_common`` focused on template helpers (formatters, ledger
selection, view-models) and concentrates the SQL here next to the other
``*_service`` modules.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuthToken, Device, Expense
from app.services.expense_service import NOTIFICATION_DRAFT_SOURCE_PREFIX
from app.services.spending_contract_service import (
    accounting_zone,
    clean_month,
    month_bounds_utc,
    stat_time,
    stat_time_expr,
)
from app.services.time_service import now_utc

# Keys are the literal ``Expense.source`` values the write paths persist
# (uploads.py, expense_service create, csv import, bill-split accept) — the
# previous key set (ios_upload_link/android_upload/manual/web) matched nothing
# in the real value domain, so every page showed 未知/其他.
SOURCE_LABELS: dict[str, str] = {
    "iPhone截图": "iPhone",
    "Android截图": "Android",
    "手动记账": "手动",
    "CSV导入": "CSV",
    "bill_split_received": "拆账",
}


def source_label(source: str | None, default: str) -> str:
    """Display label for an ``Expense.source`` value. Notification drafts are
    a prefixed family (``通知草稿:微信`` …) matched by prefix."""
    cleaned = (source or "").strip()
    if not cleaned:
        return default
    if cleaned.startswith(NOTIFICATION_DRAFT_SOURCE_PREFIX):
        return "通知"
    return SOURCE_LABELS.get(cleaned, default)


def sidebar_counts(db: Session, ledger_id: str) -> tuple[int, int]:
    """Cheap counts for the sidebar nav badges (pending + suspected duplicates).

    Avoids loading full ``list_pending()`` rows on pages that don't need them.
    """
    pending_count = int(
        db.scalar(
            select(func.count(Expense.id))
            .where(Expense.tenant_id == ledger_id)
            .where(Expense.status == "pending")
        )
        or 0
    )
    suspected_count = int(
        db.scalar(
            select(func.count(Expense.id))
            .where(Expense.tenant_id == ledger_id)
            .where(Expense.status == "pending")
            .where(Expense.duplicate_status == "suspected")
        )
        or 0
    )
    return pending_count, suspected_count


def trend14_amounts(db: Session, ledger_id: str) -> list[dict]:
    """近 14 个日历日（含今天）的每日确认金额，按 expense_time/confirmed_at 聚合。"""
    zone = _web_stats_zone()
    today = now_utc().astimezone(zone).date()
    start = today - timedelta(days=13)
    start_utc = datetime(start.year, start.month, start.day, tzinfo=zone).astimezone(UTC)
    end_day = today + timedelta(days=1)
    end_utc = datetime(end_day.year, end_day.month, end_day.day, tzinfo=zone).astimezone(UTC)
    expense_time = stat_time_expr()
    expenses = db.scalars(
        select(Expense)
        .where(Expense.tenant_id == ledger_id)
        .where(Expense.status == "confirmed")
        .where(Expense.amount_cents.is_not(None))
        .where(expense_time >= start_utc)
        .where(expense_time < end_utc)
    )
    by_day: dict[str, int] = defaultdict(int)
    for expense in expenses:
        when = stat_time(expense)
        if when is None or expense.amount_cents is None:
            continue
        by_day[when.astimezone(zone).strftime("%m-%d")] += int(expense.amount_cents)
    result: list[dict] = []
    for i in range(14):
        d = start + timedelta(days=i)
        label = d.strftime("%m-%d")
        result.append({
            "d": label,
            "amount_yuan": by_day.get(label, 0) / 100.0,
            "amount_cents": by_day.get(label, 0),
        })
    return result


def confirmed_by_day(db: Session, ledger_id: str, month: str) -> list[dict]:
    """已确认账单在指定月内的每日金额，用于日历热力图。"""
    month = _clean_month_filter(month)
    zone = _web_stats_zone()
    start_utc, end_utc = _month_bounds(month, zone)
    expense_time = stat_time_expr()
    expenses = db.scalars(
        select(Expense)
        .where(Expense.tenant_id == ledger_id)
        .where(Expense.status == "confirmed")
        .where(Expense.amount_cents.is_not(None))
        .where(expense_time >= start_utc)
        .where(expense_time < end_utc)
    )
    by_day: dict[str, dict[str, int]] = defaultdict(lambda: {"amount_cents": 0, "count": 0})
    for expense in expenses:
        when = stat_time(expense)
        if when is None or expense.amount_cents is None:
            continue
        key = when.astimezone(zone).date().isoformat()
        by_day[key]["amount_cents"] += int(expense.amount_cents)
        by_day[key]["count"] += 1
    return [
        {
            "date": day,
            "amount_cents": values["amount_cents"],
            "amount_yuan": values["amount_cents"] / 100.0,
            "count": values["count"],
        }
        for day, values in sorted(by_day.items())
    ]


def source_breakdown(db: Session, ledger_id: str, month: str | None) -> list[dict]:
    """指定月的已确认账单来源占比。返回 [{'label', 'count', 'percent'}]。"""
    q = (
        select(Expense.source, func.count(Expense.id))
        .where(Expense.tenant_id == ledger_id)
        .where(Expense.status == "confirmed")
    )
    if month:
        month = _clean_month_filter(month)
        zone = _web_stats_zone()
        start_utc, end_utc = _month_bounds(month, zone)
        expense_time = stat_time_expr()
        q = q.where(expense_time >= start_utc).where(expense_time < end_utc)
    q = q.group_by(Expense.source)
    rows = list(db.execute(q))
    total = sum(int(c or 0) for _, c in rows) or 1
    # Aggregate AFTER labeling: distinct source values can share one display
    # label (every 通知草稿:* channel → 通知), and the previous dead key set
    # produced multiple identically-named 其他 rows.
    by_label: dict[str, int] = {}
    for s, c in rows:
        label = source_label(s, "其他")
        by_label[label] = by_label.get(label, 0) + int(c)
    return [
        {
            "label": label,
            "count": count,
            "percent": int(round(count / total * 100)),
        }
        for label, count in sorted(by_label.items(), key=lambda kv: -kv[1])
    ]


def _clean_month_filter(month: str) -> str:
    return clean_month(month)


def _web_stats_zone() -> ZoneInfo:
    return accounting_zone()


def _month_bounds(month: str, zone: ZoneInfo) -> tuple[datetime, datetime]:
    return month_bounds_utc(month, zone.key)


def recent_expense_count(db: Session, ledger_id: str, since: datetime) -> int:
    """Number of expenses created on/after ``since`` for the given ledger."""
    return int(
        db.scalar(
            select(func.count())
            .select_from(Expense)
            .where(Expense.tenant_id == ledger_id)
            .where(Expense.created_at >= since)
        )
        or 0
    )


def active_device_count(db: Session, ledger_id: str) -> int:
    """Number of distinct active devices bound to ``ledger_id``.

    A device is active when at least one non-revoked AuthToken exists for the
    ledger and the device itself has not been revoked.
    """
    return int(
        db.scalar(
            select(func.count(func.distinct(Device.id)))
            .select_from(Device)
            .join(AuthToken, AuthToken.device_id == Device.id)
            .where(AuthToken.ledger_id == ledger_id)
            .where(AuthToken.revoked_at.is_(None))
            .where(Device.revoked_at.is_(None))
        )
        or 0
    )
