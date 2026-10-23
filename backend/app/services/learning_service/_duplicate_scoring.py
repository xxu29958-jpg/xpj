"""Duplicate feedback history and the shared deterministic candidate owner."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Expense, LedgerLearningEvent
from app.services.duplicate_evidence import DuplicateCandidateScore
from app.services.learning_service._algorithm_registry import DUPLICATE_CANDIDATE
from app.services.learning_service._source_eligibility import _event_payload, eligible_feedback
from app.services.time_service import now_utc

# Source of truth lives in the algorithm registry.
ALGORITHM_VERSION = DUPLICATE_CANDIDATE.current_version

DEFAULT_REJECT_HORIZON_DAYS = 90


def duplicate_feedback_expense_ids(db: Session, *, tenant_id: str, expenses: Iterable[Expense], actor_account_id: int | None = None) -> set[int]:
    """A history label belongs only to the pair currently being reviewed."""
    pairs = {row.id: row.duplicate_of_id for row in expenses if row.tenant_id == tenant_id and row.duplicate_of_id is not None}
    if not pairs or actor_account_id is None:
        return set()
    observed_at = now_utc()
    cutoff = observed_at - timedelta(days=DEFAULT_REJECT_HORIZON_DAYS)
    found = db.scalars(
        select(LedgerLearningEvent)
        .where(LedgerLearningEvent.tenant_id == tenant_id)
        .where(LedgerLearningEvent.subject_kind == "expense")
        .where(LedgerLearningEvent.subject_id.in_(pairs))
        .where(LedgerLearningEvent.event_type == "reject")
        .where(LedgerLearningEvent.created_at >= cutoff)
        .where(LedgerLearningEvent.created_at <= observed_at)
        .where(
            LedgerLearningEvent.signal_type
            == DUPLICATE_CANDIDATE.decision_type
        )
    )
    return {row.subject_id for row in eligible_feedback(db, tenant_id=tenant_id, events=list(found),
        actor_account_id=actor_account_id) if _event_payload(row).get("candidate_id") == pairs.get(row.subject_id)}


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
