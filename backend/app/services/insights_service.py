"""v0.4-alpha3 — Smart Ledger Engine insights.

Read-only aggregations that surface candidates / suggestions to the user.
Nothing in this module writes to the database. Nothing here auto-creates
recurring records, budgets, or confirms expenses.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Expense
from app.services.merchant_service import normalize_merchant
from app.services.time_service import ensure_utc, local_month_label


def _display_merchant(values: Iterable[str]) -> str:
    # Pick the most-frequent original spelling as the display label, with the
    # shortest as tie-breaker — Monarch-style "use what user typed most".
    counts: dict[str, int] = defaultdict(int)
    for raw in values:
        counts[raw] += 1
    if not counts:
        return ""
    return sorted(counts.items(), key=lambda pair: (-pair[1], len(pair[0]), pair[0]))[0][0]


# --- Recurring candidates (T24) -------------------------------------------


def _amount_close(values: list[int]) -> tuple[bool, int]:
    """Return ``(within_tolerance, representative_amount)``.

    A group is considered "amount-stable" when ``max - min <= 15% * max``.
    Representative amount is the most recent one (caller passes values in
    chronological order, oldest first).
    """
    if not values:
        return False, 0
    hi = max(values)
    lo = min(values)
    if hi <= 0:
        return False, 0
    tolerance = max(int(hi * 0.15), 1)
    representative = values[-1]
    return (hi - lo) <= tolerance, representative


def recurring_candidates(
    db: Session,
    *,
    tenant_id: str,
    timezone_name: str | None = None,
    min_occurrences: int = 2,
) -> list[dict]:
    """Detect merchants that recur across distinct months with stable amounts.

    Algorithm v1:
      - Scan confirmed expenses for this tenant.
      - Group by normalized merchant.
      - Within each group, require >= ``min_occurrences`` distinct month buckets.
      - Require amount range within 15% of the max (T24 spec).
      - Output: merchant display label, representative amount (most recent),
        occurrence_count (distinct months), last_seen_at, confidence, reason.
    Never writes.
    """
    tz = (timezone_name or "").strip() or get_settings().ocr_default_timezone

    expenses = list(
        db.scalars(
            select(Expense)
            .where(Expense.tenant_id == tenant_id)
            .where(Expense.status == "confirmed")
            .where(Expense.merchant.is_not(None))
        )
    )

    # Bucket: normalized_key -> list of (datetime, amount_cents, raw_merchant)
    grouped: dict[str, list[tuple[datetime, int, str]]] = defaultdict(list)
    for expense in expenses:
        merchant_raw = (expense.merchant or "").strip()
        key = normalize_merchant(merchant_raw)
        if not key:
            continue
        when = ensure_utc(expense.expense_time) or ensure_utc(expense.confirmed_at)
        if when is None:
            continue
        amount = int(expense.amount_cents or 0)
        if amount <= 0:
            continue
        grouped[key].append((when, amount, merchant_raw))

    candidates: list[dict] = []
    for _, entries in grouped.items():
        entries.sort(key=lambda triple: triple[0])
        # distinct month labels
        month_labels: set[str] = set()
        for when, _amount, _raw in entries:
            label = local_month_label(when, tz)
            if label:
                month_labels.add(label)
        occurrence_count = len(month_labels)
        if occurrence_count < min_occurrences:
            continue
        amounts = [amount for _, amount, _ in entries]
        amount_ok, representative = _amount_close(amounts)
        if not amount_ok:
            continue
        last_when = entries[-1][0]
        display = _display_merchant(raw for _, _, raw in entries)
        confidence = "high" if occurrence_count >= 3 else "medium"
        reason = (
            f"近 {occurrence_count} 个月金额接近，每月出现"
            if occurrence_count >= 3
            else f"已连续 {occurrence_count} 个月出现，金额接近"
        )
        candidates.append(
            {
                "merchant": display,
                "amount_cents": int(representative),
                "occurrence_count": occurrence_count,
                "last_seen_at": last_when,
                "confidence": confidence,
                "reason": reason,
            }
        )
    candidates.sort(
        key=lambda item: (-item["occurrence_count"], -item["amount_cents"], item["merchant"])
    )
    return candidates
