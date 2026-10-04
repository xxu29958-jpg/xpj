"""Small, side-effect-free calculations used by the Web dashboard."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.money_contract import projection_sum_to_int, projection_values_sum_to_int
from app.services.recurring_service import list_recurring_items


def dashboard_percentage_tenths(part: int | None, total: int) -> int | None:
    """Project a drawable share without rounding money through floating point."""
    if part is None or part < 0 or total <= 0:
        return None
    return (part * 1000 + total // 2) // total


def dashboard_category_groups(categories: list[dict]) -> list[dict]:
    """Keep five named categories and fold a fully known tail into Other."""
    if len(categories) <= 6 or any(item["amount_cents"] is None for item in categories):
        return categories
    head, tail = categories[:5], categories[5:]
    tail_cents = projection_values_sum_to_int(
        (item["amount_cents"] for item in tail), label="web.category_tail"
    )
    tail_count = sum(int(item["count"]) for item in tail)
    for item in head:
        if item["category"] == "其他":
            item["amount_cents"] = projection_sum_to_int(
                projection_sum_to_int(item["amount_cents"], label="web.category_other") + tail_cents,
                label="web.category_other_merged",
            )
            item["count"] = int(item["count"]) + tail_count
            return head
    return [*head, {"category": "其他", "amount_cents": tail_cents, "count": tail_count}]


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
) -> tuple[int | None, int | None, int | None, str, int | None]:
    current = None if stats["total_amount_cents"] is None else projection_sum_to_int(
        stats["total_amount_cents"],
        label="web.dashboard_total",
    )
    previous = (
        None if previous_stats["total_amount_cents"] is None else projection_sum_to_int(
            previous_stats["total_amount_cents"],
            label="web.dashboard_previous_total",
        )
        if previous_stats
        else 0
    )
    if current is None or previous is None:
        return current, previous, None, "unavailable", None
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
