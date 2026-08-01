"""Small, side-effect-free calculations used by the Web dashboard."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.money_contract import projection_sum_to_int
from app.services.recurring_service import list_recurring_items


def previous_month_string(month: str) -> str | None:
    try:
        year_text, month_text = month.split("-", 1)
        year = int(year_text)
        month_number = int(month_text)
    except (TypeError, ValueError):
        return None
    if not 1 <= month_number <= 12:
        return None
    if month_number == 1:
        return f"{year - 1:04d}-12"
    return f"{year:04d}-{month_number - 1:02d}"


def recurring_status_counts(db: Session, ledger_id: str) -> tuple[int, int]:
    rows = list_recurring_items(
        db,
        tenant_id=ledger_id,
        include_archived=False,
    )
    active = sum(1 for item in rows if item.status == "active")
    paused = sum(1 for item in rows if item.status == "paused")
    return active, paused


def dashboard_month_delta(
    stats: dict,
    previous_stats: dict | None,
) -> tuple[int, int, int, str, int | None]:
    current = projection_sum_to_int(
        stats["total_amount_cents"],
        label="web.dashboard_total",
    )
    previous = (
        projection_sum_to_int(
            previous_stats["total_amount_cents"],
            label="web.dashboard_previous_total",
        )
        if previous_stats
        else 0
    )
    delta = projection_sum_to_int(
        current - previous,
        label="web.dashboard_delta",
    )
    if previous <= 0:
        return current, previous, delta, "none", None
    if delta == 0:
        return current, previous, delta, "flat", 0
    direction = "up" if delta > 0 else "down"
    percent = (abs(delta) * 100 + previous // 2) // previous
    return current, previous, delta, direction, percent
