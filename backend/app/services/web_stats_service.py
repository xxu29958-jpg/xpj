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
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuthToken, Device, Expense, LedgerMember
from app.services.currency_binding_service import require_runtime_home_currency_code
from app.services.currency_common import (
    minor_amount_major_number,
)
from app.services.data_quality_service import is_usable_pending_merchant
from app.services.expense_service import NOTIFICATION_DRAFT_SOURCE_PREFIX
from app.services.money_projection_service import sum_projected_amounts
from app.services.spending_contract_service import (
    accounting_zone,
    clean_month,
    confirmed_query,
    month_bounds_utc,
)
from app.services.spending_projection_service import entry_gaps, read_projected_entries
from app.services.time_service import now_utc

# Keys are the literal ``Expense.source`` values the write paths persist
# (uploads.py, expense_service create, csv import, bill-split accept) — the
# previous key set (ios_upload_link/android_upload/manual/web) matched nothing
# in the real value domain, so every page showed 未知/其他.
SOURCE_LABELS: dict[str, str] = {
    "iPhone截图": "iPhone",
    "Android截图": "Android",
    "网页上传": "网页",
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


def confirmed_by_day(
    db: Session,
    ledger_id: str,
    month: str,
    *,
    currency_code: str | None = None,
    tag: str | None = None,
) -> list[dict]:
    """Project each recorded contribution before grouping calendar days."""
    month = _clean_month_filter(month)
    zone = _web_stats_zone()
    home = currency_code or require_runtime_home_currency_code(db)
    entries = read_projected_entries(db, tenant_id=ledger_id, ranges=[month_bounds_utc(month, zone.key)],
        timezone_name=zone.key, home=home, tag=tag)
    days = defaultdict(list)
    for entry in entries:
        days[entry.stream_date.isoformat()].append(entry)
    result = []
    for day, rows in sorted(days.items()):
        amount = sum_projected_amounts((row.amount_cents for row in rows), label="web_stats.calendar_day")
        result.append({"date": day, "home_currency_code": home, "amount_cents": amount,
            "amount_yuan": None if amount is None else minor_amount_major_number(amount, home),
            "count": len(rows), "missing_rates": entry_gaps(rows)})
    return result


def source_breakdown(
    db: Session,
    ledger_id: str,
    month: str | None,
    *,
    tag: str | None = None,
) -> list[dict]:
    """指定月的已确认账单来源占比。返回 [{'label', 'count', 'percent'}]。"""
    zone = _web_stats_zone()
    filtered = confirmed_query(
        tenant_id=ledger_id,
        month=month,
        tag=tag,
        timezone_name=zone.key,
    ).subquery()
    q = (
        select(filtered.c.source, func.count(filtered.c.id))
        .select_from(filtered)
        .group_by(filtered.c.source)
    )
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
            "percent": (count * 100 + total // 2) // total,
        }
        for label, count in sorted(by_label.items(), key=lambda kv: -kv[1])
    ]


def _clean_month_filter(month: str) -> str:
    return clean_month(month)


def _web_stats_zone() -> ZoneInfo:
    return accounting_zone()


def _month_bounds(month: str, zone: ZoneInfo) -> tuple[datetime, datetime]:
    return month_bounds_utc(month, zone.key)


def pending_quality_counts(db: Session, ledger_id: str) -> dict[str, int]:
    """Dashboard pending-card counts without materializing full pending rows.

    total / needs-amount / suspected are plain COUNT()s with the same predicates
    as ``list_pending`` + the dashboard card block; needs-merchant projects only
    the merchant column because ``is_usable_pending_merchant`` is a Kotlin-ported
    Unicode predicate that must stay byte-exact (PR #253 R3 — count semantics
    identical to the old materialize-then-count caliber, pinned by tests).
    """
    pending_count, suspected = sidebar_counts(db, ledger_id)
    needs_amount = int(
        db.scalar(
            select(func.count(Expense.id))
            .where(Expense.tenant_id == ledger_id)
            .where(Expense.status == "pending")
            .where(Expense.amount_cents.is_(None))
        )
        or 0
    )
    merchants = db.scalars(
        select(Expense.merchant)
        .where(Expense.tenant_id == ledger_id)
        .where(Expense.status == "pending")
    ).all()
    needs_merchant = sum(1 for merchant in merchants if not is_usable_pending_merchant(merchant))
    return {
        "pending_count": pending_count,
        "needs_amount_count": needs_amount,
        "needs_merchant_count": needs_merchant,
        "suspected_duplicate_count": suspected,
    }


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


def recent_confirmed_expense_count(db: Session, ledger_id: str, since: datetime) -> int:
    """Number of CONFIRMED expenses created on/after ``since``.

    This is the caliber the overview 最近新增 card links to (/web/confirmed):
    count and destination must agree (PR #253 R2) — the all-status
    ``recent_expense_count`` could show a positive number while the confirmed
    list it linked to was empty.
    """
    return int(
        db.scalar(
            select(func.count())
            .select_from(Expense)
            .where(Expense.tenant_id == ledger_id)
            .where(Expense.created_at >= since)
            .where(Expense.status == "confirmed")
        )
        or 0
    )


def active_device_count(db: Session, ledger_id: str) -> int:
    """Number of active account devices authorized for ``ledger_id``.

    CurrentLedger is client context, so an AuthToken's compatibility default
    cannot define ledger reachability. Active Membership does.

    PR #253 R4-4: only tokens that can actually authenticate count — session
    scopes (``app``/``admin``), not staged ``desktop_pending`` credentials, and
    not expired-but-unrevoked tokens (``expires_at`` null or in the future).
    """
    now = now_utc()
    return int(
        db.scalar(
            select(func.count(func.distinct(Device.id)))
            .select_from(Device)
            .join(AuthToken, AuthToken.device_id == Device.id)
            .join(
                LedgerMember,
                (LedgerMember.account_id == Device.account_id)
                & (LedgerMember.ledger_id == ledger_id),
            )
            .where(AuthToken.revoked_at.is_(None))
            .where(AuthToken.scope.in_(("app", "admin")))
            .where((AuthToken.expires_at.is_(None)) | (AuthToken.expires_at > now))
            .where(Device.revoked_at.is_(None))
            .where(LedgerMember.disabled_at.is_(None))
        )
        or 0
    )
