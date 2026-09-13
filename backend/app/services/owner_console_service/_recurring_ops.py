"""Recurring-items summary view-model used by the Owner Console index card."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models import Expense, RecurringItem
from app.services.owner_console_service._common import _owner_ledger_ids
from app.services.recurring_occurrence_query import next_due_dates_for_ledgers
from app.services.spending_contract_service import accounting_zone
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


def _empty_recurring_ops() -> RecurringOpsVM:
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


def _active_due_dates(db: Session, ledger_ids: list[str]) -> list[date]:
    return next_due_dates_for_ledgers(db, tenant_ids=ledger_ids)


def _notification_draft_filter() -> ColumnElement[bool]:
    return Expense.source.like("通知草稿:%")


def _count_notification_pending(db: Session, ledger_ids: list[str]) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(Expense)
            .where(Expense.tenant_id.in_(ledger_ids))
            .where(_notification_draft_filter())
            .where(Expense.status == "pending")
        )
        or 0
    )


def _count_notification_recent(
    db: Session, ledger_ids: list[str], *, now: datetime
) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(Expense)
            .where(Expense.tenant_id.in_(ledger_ids))
            .where(_notification_draft_filter())
            .where(Expense.created_at >= now - timedelta(hours=24))
        )
        or 0
    )


def _count_notification_incomplete(db: Session, ledger_ids: list[str]) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(Expense)
            .where(Expense.tenant_id.in_(ledger_ids))
            .where(_notification_draft_filter())
            .where(Expense.status == "pending")
            .where((Expense.amount_cents.is_(None)) | (Expense.merchant.is_(None)))
        )
        or 0
    )


def get_recurring_ops(db: Session) -> RecurringOpsVM:
    ledger_ids = _owner_ledger_ids(db)
    if not ledger_ids:
        return _empty_recurring_ops()

    now = now_utc()
    today = now.astimezone(accounting_zone()).date()
    soon = today + timedelta(days=7)
    due_dates = _active_due_dates(db, ledger_ids)
    return RecurringOpsVM(
        active_count=_count_recurring(db, ledger_ids, "active"),
        paused_count=_count_recurring(db, ledger_ids, "paused"),
        archived_count=_count_recurring(db, ledger_ids, "archived"),
        due_soon_count=sum(today <= day <= soon for day in due_dates),
        overdue_count=sum(day < today for day in due_dates),
        notification_pending_count=_count_notification_pending(db, ledger_ids),
        notification_recent_24h_count=_count_notification_recent(db, ledger_ids, now=now),
        notification_incomplete_count=_count_notification_incomplete(db, ledger_ids),
    )
