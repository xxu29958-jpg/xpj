"""Confirmed spending aggregate for the discretionary budget formula."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.services.spending_contract_service import confirmed_amount_query


def total_confirmed_spent_cents(
    db: Session,
    *,
    tenant_id: str,
    month: str,
    timezone_name: str | None = None,
) -> int:
    """Sum confirmed expenses for the accounting month.

    This uses the shared spending contract so late income backfills and already
    confirmed expenses meet on the same month boundary as stats and budgets.
    """

    filtered = confirmed_amount_query(
        tenant_id=tenant_id,
        month=month,
        timezone_name=timezone_name,
    ).subquery()
    total = db.scalar(
        select(func.coalesce(func.sum(filtered.c.amount_cents), 0)).select_from(filtered)
    )
    return int(total or 0)
