"""Personal category advice from explicit, independent examples.

V3 limits recall to the same member, ledger, merchant and recorded purpose
within 180 days. Defaults, accepted advice and single-use choices do not vote.
Current taxonomy, source edits, reversal, withdrawal and version isolation
remain authoritative. Each transaction contributes at most once; ties and
insufficient support yield no advice. Context-matched independent rejections
can suppress a candidate. Neither this reader nor its advice changes facts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Expense, LedgerLearningEvent
from app.services.learning_service._algorithm_registry import (
    CATEGORY_SUGGESTION,
    canonical_marker_hash,
)
from app.services.learning_service._category_memory import (
    category_merchant_filter,
    independent_category_rejects,
    personal_category_counts,
)
from app.services.learning_service._policy import policy_enabled
from app.services.learning_service._source_eligibility import eligible_feedback
from app.services.ledger_calendar_service import current_calendar
from app.services.time_service import now_utc, strict_zone

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
    merchant_filter,
    category: str,
    horizon_days: int, actor_account_id: int | None = None,
    expense_id: int | None = None,
) -> int:
    """Count user rejects of (merchant, category) in the recent past.

    v1.2 ops: filter on the indexed ``(signal_type, signal_hash)``
    pair via ``CATEGORY_SUGGESTION.build_marker({"category": category})``.
    Legacy rows are backfilled by migration ``c5b9a324c535`` so the
    OR / LIKE fallback was removed — this query now goes through the
    composite index unconditionally.
    """

    cutoff = now_utc() - timedelta(days=max(horizon_days, 0))
    marker = CATEGORY_SUGGESTION.build_marker({"category": category})
    indexed_hash = canonical_marker_hash(marker)
    events = list(db.scalars(
        select(LedgerLearningEvent)
        .join(Expense, Expense.id == LedgerLearningEvent.subject_id)
        .where(LedgerLearningEvent.tenant_id == tenant_id)
        .where(Expense.tenant_id == tenant_id)
        .where(LedgerLearningEvent.subject_kind == "expense")
        .where(LedgerLearningEvent.subject_id.is_not(None))
        .where(LedgerLearningEvent.event_type.in_(("reject", "edit")))
        .where(LedgerLearningEvent.created_at >= cutoff)
        .where(LedgerLearningEvent.created_at <= now_utc())
        .where(LedgerLearningEvent.actor_account_id == actor_account_id)
        .where(
            LedgerLearningEvent.signal_type
            == CATEGORY_SUGGESTION.decision_type
        )
        .where(LedgerLearningEvent.signal_hash == indexed_hash)
        .where(merchant_filter)
        .order_by(LedgerLearningEvent.id.desc()).limit(200)
    ))
    valid = eligible_feedback(db, tenant_id=tenant_id, events=events, actor_account_id=actor_account_id)
    return independent_category_rejects(db, tenant_id=tenant_id, events=valid, expense_id=expense_id)


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
    actor_account_id: int | None = None,
) -> CategorySuggestion | None:
    """Return the historically-most-frequent category for ``merchant``.

    ``expense_id`` excludes self-matches and supplies the proposed expense's
    purpose, items, currency and accounts for scoped recall.
    """

    normalised = _normalised_merchant(merchant)
    if not normalised or actor_account_id is None or not policy_enabled(db, tenant_id=tenant_id, decision_type=CATEGORY_SUGGESTION.decision_type,
            version=ALGORITHM_VERSION, axis="new_suggestions"):
        return None

    zone = strict_zone(current_calendar(db, ledger_id=tenant_id).timezone_name)
    observed_at = now_utc()
    current_date = observed_at.astimezone(zone).date()
    cutoff = current_date - timedelta(days=max(look_back_days, 0))
    merchant_filter = category_merchant_filter(db, tenant_id=tenant_id, merchant=normalised)
    rows = personal_category_counts(db, tenant_id=tenant_id, merchant_filter=merchant_filter,
        actor_account_id=actor_account_id, expense_id=expense_id, cutoff=cutoff,
        current_date=current_date, observed_at=observed_at)
    if not rows:
        return None
    total = sum(count for _, count in rows)
    top_category, top_count = rows[0]
    if not top_category or top_count < max(min_samples, 1):
        return None
    if len(rows) > 1 and rows[1][1] == top_count:
        return None

    rejects = _count_recent_rejects(
        db,
        tenant_id=tenant_id,
        merchant_filter=merchant_filter,
        category=top_category,
        horizon_days=feedback_horizon_days, actor_account_id=actor_account_id,
        expense_id=expense_id,
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
