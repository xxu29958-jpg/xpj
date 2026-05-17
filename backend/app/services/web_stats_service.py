"""DB-level statistics queries used by the /web surface.

These functions were previously private helpers inside
``app/routes/web_common.py``. They were doing direct ORM queries in the route
layer, which violates the routes → services → models layering. Extracting
them keeps ``web_common`` focused on template helpers (formatters, ledger
selection, view-models) and concentrates the SQL here next to the other
``*_service`` modules.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import AuthToken, Device, Expense
from app.services.time_service import normalize_month_label, now_utc


SOURCE_LABELS: dict[str, str] = {
    "ios_upload_link": "iPhone",
    "android_upload": "Android",
    "manual": "手动",
    "web": "网页",
}


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
    today = now_utc().astimezone().date()
    start = today - timedelta(days=13)
    expense_time = func.coalesce(Expense.expense_time, Expense.confirmed_at)
    rows = db.execute(
        select(func.strftime("%m-%d", expense_time), func.coalesce(func.sum(Expense.amount_cents), 0))
        .where(Expense.tenant_id == ledger_id)
        .where(Expense.status == "confirmed")
        .where(func.date(expense_time) >= start.isoformat())
        .where(func.date(expense_time) <= today.isoformat())
        .group_by(func.strftime("%m-%d", expense_time))
    )
    by_day: dict[str, int] = {label: int(amt or 0) for label, amt in rows}
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
    expense_time = func.coalesce(Expense.expense_time, Expense.confirmed_at)
    rows = db.execute(
        select(
            func.strftime("%Y-%m-%d", expense_time),
            func.coalesce(func.sum(Expense.amount_cents), 0),
            func.count(Expense.id),
        )
        .where(Expense.tenant_id == ledger_id)
        .where(Expense.status == "confirmed")
        .where(func.strftime("%Y-%m", expense_time) == month)
        .group_by(func.strftime("%Y-%m-%d", expense_time))
    )
    return [
        {"date": d, "amount_cents": int(amt or 0), "amount_yuan": int(amt or 0) / 100.0, "count": int(cnt)}
        for d, amt, cnt in rows
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
        expense_time = func.coalesce(Expense.expense_time, Expense.confirmed_at)
        q = q.where(func.strftime("%Y-%m", expense_time) == month)
    q = q.group_by(Expense.source)
    rows = list(db.execute(q))
    total = sum(int(c or 0) for _, c in rows) or 1
    return [
        {
            "label": SOURCE_LABELS.get((s or "").strip(), "其他"),
            "count": int(c),
            "percent": int(round(int(c) / total * 100)),
        }
        for s, c in sorted(rows, key=lambda r: -int(r[1] or 0))
    ]


def _clean_month_filter(month: str) -> str:
    cleaned = normalize_month_label(month)
    if cleaned is None:
        raise AppError("invalid_request", status_code=422)
    return cleaned


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
