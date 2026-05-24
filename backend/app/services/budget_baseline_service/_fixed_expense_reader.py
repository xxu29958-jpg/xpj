"""Aggregate active recurring_items into the fixed-expense leg of
"本月可自由支配".

``recurring_items`` already tracks monthly outgoing bills / subscriptions
(see PR-6 commit notes for why we don't duplicate this in a new table).
This module sums the ``baseline_amount_cents`` of active monthly rows
so the discretionary endpoint and budget advisor inputs can share one
canonical fixed-expense total.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ledger_scope import add_ledger_scope
from app.models import RecurringItem


def total_active_recurring_monthly_cents(db: Session, *, tenant_id: str) -> int:
    """Sum of active monthly recurring outflows for the tenant."""
    total = db.scalar(
        add_ledger_scope(
            select(func.coalesce(func.sum(RecurringItem.baseline_amount_cents), 0)),
            RecurringItem,
            tenant_id,
        )
        .where(RecurringItem.status == "active")
        .where(RecurringItem.frequency == "monthly")
    )
    return int(total or 0)
