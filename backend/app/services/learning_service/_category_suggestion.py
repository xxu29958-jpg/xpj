"""v1.2 P1 — category self-learning suggestions.

Read-only service that mines confirmed expenses for the user's
historical merchant→category mapping and turns it into a suggestion.
The suggestion is recorded in ``algorithm_decisions`` (via
:func:`learning_service.record_decision`) and surfaced in the pending
review UI — it never auto-mutates the expense row.

Algorithm v1 (``algorithm_version='category-history-v1'``):

* Find confirmed expenses in the same tenant with the same merchant
  (case-insensitive exact match after stripping). Limit to the last
  ``look_back_days`` to keep the recency horizon explicit.
* Aggregate by category. If the top category has at least
  ``min_samples`` confirmed expenses, that's the candidate. ``score``
  is the ratio top_count / total within the lookback window.
* Down-weight: if the user has rejected this exact (merchant,
  category) suggestion ``reject_threshold`` times or more in the past
  ``feedback_horizon_days``, the suggestion is suppressed entirely.
  This is where the "反馈带来个性化" loop closes.

Returns ``None`` whenever there's no defensible suggestion (no
merchant, not enough samples, suppressed by feedback). Callers should
treat that as "no AI hint this time" — the rule-based ``classify_expense``
remains the existing autoclassification path.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models import Expense, LedgerLearningEvent
from app.services.learning_service._algorithm_registry import (
    CATEGORY_SUGGESTION,
)
from app.services.spending_contract_service import stat_time_expr
from app.services.time_service import now_utc

# Source of truth lives in the algorithm registry. Keep the
# module-level constant as a shim so callers / tests that import
# ``ALGORITHM_VERSION`` from this module don't have to change.
ALGORITHM_VERSION = CATEGORY_SUGGESTION.current_version
DEFAULT_MIN_SAMPLES = 3
DEFAULT_LOOK_BACK_DAYS = 180
DEFAULT_REJECT_THRESHOLD = 2
DEFAULT_FEEDBACK_HORIZON_DAYS = 90


@dataclass(frozen=True)
class CategorySuggestion:
    """Result of one suggestion computation.

    ``score`` is the share of confirmed expenses for this merchant
    that landed in this category, clamped to [0, 1]. ``sample_size``
    lets the UI render "based on N past entries" so the user
    understands where the suggestion came from.
    """

    category: str
    score: float
    sample_size: int
    algorithm_version: str = ALGORITHM_VERSION


def _normalised_merchant(value: str | None) -> str:
    return (value or "").strip().casefold()


def _count_recent_rejects(
    db: Session,
    *,
    tenant_id: str,
    merchant: str,
    category: str,
    horizon_days: int,
) -> int:
    """Count user rejects of (merchant, category) in the recent past.

    We filter at the row level on ``after_payload`` (where the user's
    chosen replacement lives) using a JSON substring match — the
    payloads are sort-key JSON so the substring is deterministic.
    Slow on huge tables but the horizon is bounded; we'll move to an
    indexed marker column if this ever shows up in slow-query logs.
    """

    cutoff = now_utc() - timedelta(days=max(horizon_days, 0))
    # Build the expected JSON substring for a rejected suggestion:
    # the *before* payload contains the suggestion category, so look
    # for it there. ``rejected`` is the event type used by callers
    # that explicitly say "no, that's wrong" without picking a new
    # category; the merchant lookup is approximate (substring) on
    # purpose so capitalisation differences don't drop the signal.
    needle = json.dumps({"category": category}, ensure_ascii=False)
    count = db.scalar(
        select(func.count(LedgerLearningEvent.id))
        .join(Expense, Expense.id == LedgerLearningEvent.subject_id)
        .where(LedgerLearningEvent.tenant_id == tenant_id)
        .where(Expense.tenant_id == tenant_id)
        .where(LedgerLearningEvent.subject_kind == "expense")
        .where(LedgerLearningEvent.subject_id.is_not(None))
        .where(LedgerLearningEvent.event_type.in_(("reject", "edit")))
        .where(LedgerLearningEvent.created_at >= cutoff)
        .where(LedgerLearningEvent.before_payload.contains(needle))
        .where(func.lower(func.trim(Expense.merchant)) == merchant)
    )
    return int(count or 0)


def compute_category_suggestion(
    db: Session,
    *,
    tenant_id: str,
    merchant: str | None,
    expense_id: int | None = None,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    look_back_days: int = DEFAULT_LOOK_BACK_DAYS,
    reject_threshold: int = DEFAULT_REJECT_THRESHOLD,
    feedback_horizon_days: int = DEFAULT_FEEDBACK_HORIZON_DAYS,
) -> CategorySuggestion | None:
    """Return the historically-most-frequent category for ``merchant``.

    The ``expense_id`` argument is purely for excluding self-matches
    (an in-flight pending expense shouldn't vote for its own category
    if the row is somehow already in the confirmed bucket).
    """

    normalised = _normalised_merchant(merchant)
    if not normalised:
        return None

    cutoff = now_utc() - timedelta(days=max(look_back_days, 0))
    time_expr = stat_time_expr()
    conditions = [
        Expense.tenant_id == tenant_id,
        Expense.status == "confirmed",
        time_expr >= cutoff,
        func.lower(func.trim(Expense.merchant)) == normalised,
    ]
    if expense_id is not None:
        conditions.append(Expense.id != expense_id)

    rows: Iterable[tuple[str, int]] = db.execute(
        select(Expense.category, func.count())
        .where(and_(*conditions))
        .group_by(Expense.category)
        .order_by(func.count().desc())
    ).all()
    rows = list(rows)
    if not rows:
        return None
    total = sum(count for _, count in rows)
    if total < max(min_samples, 1):
        return None
    top_category, top_count = rows[0]
    if not top_category:
        return None

    rejects = _count_recent_rejects(
        db,
        tenant_id=tenant_id,
        merchant=normalised,
        category=top_category,
        horizon_days=feedback_horizon_days,
    )
    if rejects >= max(reject_threshold, 1):
        return None

    score = float(top_count) / float(total)
    return CategorySuggestion(
        category=str(top_category),
        score=score,
        sample_size=int(total),
    )


__all__ = [
    "ALGORITHM_VERSION",
    "CategorySuggestion",
    "compute_category_suggestion",
]
