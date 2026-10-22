"""Duplicate feedback history and the shared deterministic candidate owner."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Expense, LedgerLearningEvent
from app.services.duplicate_evidence import DuplicateCandidateScore, normalised_merchant
from app.services.learning_service._algorithm_registry import (
    DUPLICATE_CANDIDATE,
    canonical_marker_hash,
)
from app.services.learning_service._source_eligibility import eligible_feedback
from app.services.time_service import now_utc

# Source of truth lives in the algorithm registry.
ALGORITHM_VERSION = DUPLICATE_CANDIDATE.current_version

DEFAULT_REJECT_HORIZON_DAYS = 90


def duplicate_feedback_expense_ids(db: Session, *, tenant_id: str, expenses: Iterable[Expense], actor_account_id: int | None = None) -> set[int]:
    """Read the same scoring feedback for a whole review page in one indexed query."""
    markers = {
        row.id: canonical_marker_hash(DUPLICATE_CANDIDATE.build_marker(
            {"amount_cents": row.amount_cents, "merchant": normalised_merchant(row.merchant)}))
        for row in expenses if normalised_merchant(row.merchant) and row.amount_cents is not None
    }
    rejected = _recent_reject_hashes(db, tenant_id=tenant_id, hashes=list(set(markers.values())),
        horizon_days=DEFAULT_REJECT_HORIZON_DAYS, actor_account_id=actor_account_id)
    return {expense_id for expense_id, marker in markers.items() if marker in rejected}


def _recent_reject_hashes(db: Session, *, tenant_id: str, hashes: list[str | None], horizon_days: int, actor_account_id: int | None = None) -> set[str]:
    if not hashes:
        return set()
    cutoff = now_utc() - timedelta(days=max(horizon_days, 0))
    found = db.scalars(
        select(LedgerLearningEvent)
        .where(LedgerLearningEvent.tenant_id == tenant_id)
        .where(LedgerLearningEvent.subject_kind == "expense")
        .where(LedgerLearningEvent.event_type == "reject")
        .where(LedgerLearningEvent.created_at >= cutoff)
        .where(
            LedgerLearningEvent.signal_type
            == DUPLICATE_CANDIDATE.decision_type
        )
        .where(LedgerLearningEvent.signal_hash.in_(hashes))
    )
    return {row.signal_hash for row in eligible_feedback(db, tenant_id=tenant_id, events=list(found),
        actor_account_id=actor_account_id) if row.signal_hash is not None}


def score_duplicate_candidates(
    db: Session, *, tenant_id: str, expense: Expense, candidates: Iterable[Expense],
    reject_horizon_days: int = DEFAULT_REJECT_HORIZON_DAYS, actor_account_id: int | None = None,
) -> list[DuplicateCandidateScore]:
    """Use the same admission as badges; only explicit pair exclusions veto a pair.

    An unrelated rejection sharing merchant/amount cannot hide current evidence.
    Actor-bound feedback remains available for review and later learning evaluation.
    """
    from app.services.duplicate_service import rank_duplicate_candidates

    if expense.tenant_id != tenant_id:
        return []
    return rank_duplicate_candidates(db, expense=expense, candidates=candidates)


__all__ = ["ALGORITHM_VERSION", "DuplicateCandidateScore", "duplicate_feedback_expense_ids", "score_duplicate_candidates"]
