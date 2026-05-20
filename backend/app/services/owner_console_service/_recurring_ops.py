"""Recurring-items summary view-model used by the Owner Console index card."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Expense, RecurringItem
from app.services.owner_console_service._common import _owner_ledger_ids
from app.services.time_service import now_utc


@dataclass
class RecurringOpsVM:
    active_count: int
    paused_count: int
    archived_count: int
    due_soon_count: int
    overdue_count: int
    notification_pending_count: int
    notification_recent_24h_count: int
    notification_incomplete_count: int


def _count_recurring(db: Session, ledger_ids: list[str], status: str) -> int:
    if not ledger_ids:
        return 0
    return int(
        db.scalar(
            select(func.count())
            .select_from(RecurringItem)
            .where(RecurringItem.tenant_id.in_(ledger_ids))
            .where(RecurringItem.status == status)
        )
        or 0
    )


def get_recurring_ops(db: Session) -> RecurringOpsVM:
    ledger_ids = _owner_ledger_ids(db)
    if not ledger_ids:
        return RecurringOpsVM(
            active_count=0,
            paused_count=0,
            archived_count=0,
            due_soon_count=0,
            overdue_count=0,
            notification_pending_count=0,
            notification_recent_24h_count=0,
            notification_incomplete_count=0,
        )

    now = now_utc()
    today = now.date()
    soon = today + timedelta(days=7)
    notification_filter = Expense.source.like("通知草稿:%")
    due_soon = int(
        db.scalar(
            select(func.count())
            .select_from(RecurringItem)
            .where(RecurringItem.tenant_id.in_(ledger_ids))
            .where(RecurringItem.status == "active")
            .where(RecurringItem.next_expected_date.is_not(None))
            .where(RecurringItem.next_expected_date >= today)
            .where(RecurringItem.next_expected_date <= soon)
        )
        or 0
    )
    overdue = int(
        db.scalar(
            select(func.count())
            .select_from(RecurringItem)
            .where(RecurringItem.tenant_id.in_(ledger_ids))
            .where(RecurringItem.status == "active")
            .where(RecurringItem.next_expected_date.is_not(None))
            .where(RecurringItem.next_expected_date < today)
        )
        or 0
    )
    notification_pending = int(
        db.scalar(
            select(func.count())
            .select_from(Expense)
            .where(Expense.tenant_id.in_(ledger_ids))
            .where(notification_filter)
            .where(Expense.status == "pending")
        )
        or 0
    )
    notification_recent = int(
        db.scalar(
            select(func.count())
            .select_from(Expense)
            .where(Expense.tenant_id.in_(ledger_ids))
            .where(notification_filter)
            .where(Expense.created_at >= now - timedelta(hours=24))
        )
        or 0
    )
    notification_incomplete = int(
        db.scalar(
            select(func.count())
            .select_from(Expense)
            .where(Expense.tenant_id.in_(ledger_ids))
            .where(notification_filter)
            .where(Expense.status == "pending")
            .where((Expense.amount_cents.is_(None)) | (Expense.merchant.is_(None)))
        )
        or 0
    )
    return RecurringOpsVM(
        active_count=_count_recurring(db, ledger_ids, "active"),
        paused_count=_count_recurring(db, ledger_ids, "paused"),
        archived_count=_count_recurring(db, ledger_ids, "archived"),
        due_soon_count=due_soon,
        overdue_count=overdue,
        notification_pending_count=notification_pending,
        notification_recent_24h_count=notification_recent,
        notification_incomplete_count=notification_incomplete,
    )
