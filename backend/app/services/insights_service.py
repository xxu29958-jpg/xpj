"""v0.4-alpha3 — Smart Ledger Engine insights.

Read-only aggregations that surface candidates / suggestions to the user.
Nothing in this module writes to the database. Nothing here auto-creates
recurring records, budgets, or confirms expenses.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Expense, RecurringItem
from app.money_contract import projection_sum_to_int
from app.services.merchant_service import normalize_merchant
from app.services.time_service import ensure_utc, local_month_label, now_utc, safe_zone

_RecurringEntry = tuple[datetime, int, str]
_RecurringCandidate = dict[str, object]


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
    tolerance = max((hi * 15) // 100, 1)
    representative = values[-1]
    return (hi - lo) <= tolerance, representative


def _recurring_timezone(timezone_name: str | None) -> str:
    return (timezone_name or "").strip() or get_settings().ocr_default_timezone


# 候选扫描窗口 (PR #253 R4): 候选的可行动口径就是「近 N 个月每月出现 /
# 已连续 N 个月」(见 _recurring_reason), 扫全历史只会把多年前的老商家
# 也摆成待确认。取当前月 + 前 5 个月共 6 个月桶——既覆盖 medium/high 两档
# 置信度所需的最小数据, 又不再无界物化全量 confirmed 流水。
_CANDIDATE_LOOKBACK_MONTHS = 6


def _candidate_lookback_start(timezone_name: str) -> datetime:
    zone = safe_zone(_recurring_timezone(timezone_name))
    today = now_utc().astimezone(zone).date()
    month = today.month - (_CANDIDATE_LOOKBACK_MONTHS - 1)
    year = today.year
    while month <= 0:
        month += 12
        year -= 1
    return datetime(year, month, 1, tzinfo=zone)


def _confirmed_expenses_for_recurring(
    db: Session, *, tenant_id: str, timezone_name: str | None = None
) -> list[Expense]:
    since_local = _candidate_lookback_start(_recurring_timezone(timezone_name))
    since_utc = since_local.astimezone(UTC)
    return list(
        db.scalars(
            select(Expense)
            .where(Expense.tenant_id == tenant_id)
            .where(Expense.status == "confirmed")
            .where(Expense.merchant.is_not(None))
            # 与 _group_recurring_entries 的时间回退同口径: expense_time 优先,
            # 空则 confirmed_at。
            .where(
                or_(
                    Expense.expense_time >= since_utc,
                    and_(Expense.expense_time.is_(None), Expense.confirmed_at >= since_utc),
                )
            )
        )
    )


def _group_recurring_entries(expenses: Iterable[Expense]) -> dict[str, list[_RecurringEntry]]:
    grouped: dict[str, list[_RecurringEntry]] = defaultdict(list)
    for expense in expenses:
        merchant_raw = (expense.merchant or "").strip()
        key = normalize_merchant(merchant_raw)
        if not key:
            continue
        when = ensure_utc(expense.expense_time) or ensure_utc(expense.confirmed_at)
        if when is None:
            continue
        amount = projection_sum_to_int(
            expense.amount_cents,
            label="insights.recurring_expense",
            empty_is_zero=True,
        )
        if amount <= 0:
            continue
        grouped[key].append((when, amount, merchant_raw))
    return grouped


def _distinct_month_count(entries: list[_RecurringEntry], timezone_name: str) -> int:
    month_labels: set[str] = set()
    for when, _amount, _raw in entries:
        label = local_month_label(when, timezone_name)
        if label:
            month_labels.add(label)
    return len(month_labels)


def _recurring_reason(occurrence_count: int) -> str:
    if occurrence_count >= 3:
        return f"近 {occurrence_count} 个月金额接近，每月出现"
    return f"已连续 {occurrence_count} 个月出现，金额接近"


def _candidate_from_entries(
    entries: list[_RecurringEntry], *, timezone_name: str, min_occurrences: int
) -> _RecurringCandidate | None:
    entries.sort(key=lambda triple: triple[0])
    occurrence_count = _distinct_month_count(entries, timezone_name)
    if occurrence_count < min_occurrences:
        return None

    amounts = [amount for _, amount, _ in entries]
    amount_ok, representative = _amount_close(amounts)
    if not amount_ok:
        return None

    display = _display_merchant(raw for _, _, raw in entries)
    return {
        "merchant": display,
        "amount_cents": projection_sum_to_int(
            representative,
            label="insights.representative",
        ),
        "occurrence_count": occurrence_count,
        "last_seen_at": entries[-1][0],
        "confidence": "high" if occurrence_count >= 3 else "medium",
        "reason": _recurring_reason(occurrence_count),
    }


def _sort_recurring_candidates(
    candidates: list[_RecurringCandidate],
) -> list[_RecurringCandidate]:
    return sorted(
        candidates,
        key=lambda item: (
            -int(item["occurrence_count"]),
            -projection_sum_to_int(
                item["amount_cents"],
                label="insights.sort_amount",
            ),
            str(item["merchant"]),
        ),
    )


def recurring_candidates(
    db: Session,
    *,
    tenant_id: str,
    timezone_name: str | None = None,
    min_occurrences: int = 2,
) -> list[dict]:
    """Detect merchants that recur across distinct recent months with stable amounts.

    Algorithm v1:
      - Scan confirmed expenses within ``_CANDIDATE_LOOKBACK_MONTHS`` month buckets
        (PR #253 R4: the actionable caliber is "近 N 个月", not全历史).
      - Group by normalized merchant.
      - Within each group, require >= ``min_occurrences`` distinct month buckets.
      - Require amount range within 15% of the max (T24 spec).
      - Skip merchants already formalized as active/paused ``RecurringItem``
        (R4: claimed 过滤下推到共享装配, /web/recurring 与 overview 同口径).
      - Output: merchant display label, representative amount (most recent),
        occurrence_count (distinct months), last_seen_at, confidence, reason.
    Never writes.
    """
    tz = _recurring_timezone(timezone_name)
    grouped = _group_recurring_entries(
        _confirmed_expenses_for_recurring(db, tenant_id=tenant_id, timezone_name=timezone_name)
    )
    formal_keys = set(
        db.scalars(
            select(RecurringItem.merchant_key)
            .where(RecurringItem.tenant_id == tenant_id)
            .where(RecurringItem.status.in_(("active", "paused")))
        ).all()
    )

    candidates: list[_RecurringCandidate] = []
    for key, entries in grouped.items():
        if key in formal_keys:
            continue
        candidate = _candidate_from_entries(
            entries, timezone_name=tz, min_occurrences=min_occurrences
        )
        if candidate is not None:
            candidates.append(candidate)
    return list(_sort_recurring_candidates(candidates))


def unclaimed_recurring_candidate_count(
    db: Session, *, tenant_id: str, timezone_name: str | None = None
) -> int:
    """候选数量 (PR #253 R3/R4): claimed 过滤已下推到 ``recurring_candidates``
    共享装配, 本函数只是计数薄委托, 保留 R3 引入的调用面。"""
    return len(recurring_candidates(db, tenant_id=tenant_id, timezone_name=timezone_name))
