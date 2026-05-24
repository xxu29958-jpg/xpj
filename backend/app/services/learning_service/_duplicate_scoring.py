"""v1.2 P1 — duplicate candidate scoring.

Today's ``duplicate_service.mark_duplicate_status`` is binary: either
two expenses are flagged as suspected duplicates or they're not. This
service adds a numeric ``score`` on top so the UI can rank candidates
("very likely" vs. "maybe") instead of presenting an undifferentiated
list, and so future tooling can threshold confidently.

Score buckets (``algorithm_version='duplicate-scoring-v1'``):

* ``image_hash`` exact match → +0.5
* ``amount_cents`` exact match → +0.3
* ``merchant`` exact match (case-fold) → +0.15
* ``expense_time`` within 1h → +0.15; within 24h → +0.05
* user has previously rejected (merchant, amount) duplicate → −0.4

Final score is clamped to [0, 1]. ``reasons`` returns the per-bucket
contributions so the UI can render "图片 hash 一致 + 金额一致" rather
than an opaque number.

Scoring is *suggestion only* — calling this service never mutates the
expense row. Callers persist the result via
``learning_service.record_decision`` with
``decision_type='duplicate_candidate'`` when they want it surfaced in
the pending review UI.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Expense, LedgerLearningEvent
from app.services.learning_service._algorithm_registry import (
    DUPLICATE_CANDIDATE,
)
from app.services.time_service import ensure_utc, now_utc

# Source of truth lives in the algorithm registry.
ALGORITHM_VERSION = DUPLICATE_CANDIDATE.current_version

# Bucket weights — keep small enough that 2-3 matches comfortably stay
# below the clamp, otherwise the ranking degenerates to "everything
# saturates at 1.0".
WEIGHT_IMAGE_HASH = 0.50
WEIGHT_AMOUNT = 0.30
WEIGHT_MERCHANT = 0.15
WEIGHT_TIME_1H = 0.15
WEIGHT_TIME_24H = 0.05
WEIGHT_REJECT_PENALTY = 0.40
DEFAULT_REJECT_HORIZON_DAYS = 90


@dataclass(frozen=True)
class DuplicateCandidateScore:
    candidate_id: int
    score: float
    reasons: tuple[str, ...] = field(default_factory=tuple)
    algorithm_version: str = ALGORITHM_VERSION


def _normalised_merchant(value: str | None) -> str:
    return (value or "").strip().casefold()


def _has_recent_reject(
    db: Session,
    *,
    tenant_id: str,
    merchant: str,
    amount_cents: int | None,
    horizon_days: int,
) -> bool:
    """Look for prior user rejection of a duplicate candidate matching
    this (merchant, amount) pair. Match is JSON substring on the
    ``before_payload`` snapshot the duplicate-candidate decision wrote.
    """

    if not merchant or amount_cents is None:
        return False
    cutoff = now_utc() - timedelta(days=max(horizon_days, 0))
    needle = json.dumps(
        {"amount_cents": amount_cents, "merchant": merchant},
        sort_keys=True,
        ensure_ascii=False,
    )
    found = db.scalar(
        select(LedgerLearningEvent.id)
        .where(LedgerLearningEvent.tenant_id == tenant_id)
        .where(LedgerLearningEvent.subject_kind == "expense")
        .where(LedgerLearningEvent.event_type == "reject")
        .where(LedgerLearningEvent.created_at >= cutoff)
        .where(LedgerLearningEvent.before_payload.contains(needle))
        .limit(1)
    )
    return found is not None


def _score_one_candidate(
    expense: Expense,
    candidate: Expense,
    *,
    reject_penalty_applies: bool,
) -> DuplicateCandidateScore:
    reasons: list[str] = []
    score = 0.0

    if (
        expense.image_hash
        and candidate.image_hash
        and expense.image_hash == candidate.image_hash
    ):
        score += WEIGHT_IMAGE_HASH
        reasons.append("image_hash_match")

    if (
        expense.amount_cents is not None
        and candidate.amount_cents is not None
        and expense.amount_cents == candidate.amount_cents
    ):
        score += WEIGHT_AMOUNT
        reasons.append("amount_match")

    if _normalised_merchant(expense.merchant) and _normalised_merchant(
        expense.merchant
    ) == _normalised_merchant(candidate.merchant):
        score += WEIGHT_MERCHANT
        reasons.append("merchant_match")

    expense_time = ensure_utc(expense.expense_time) or ensure_utc(
        expense.confirmed_at
    )
    candidate_time = ensure_utc(candidate.expense_time) or ensure_utc(
        candidate.confirmed_at
    )
    if expense_time is not None and candidate_time is not None:
        delta = abs(expense_time - candidate_time)
        if delta <= timedelta(hours=1):
            score += WEIGHT_TIME_1H
            reasons.append("time_within_1h")
        elif delta <= timedelta(hours=24):
            score += WEIGHT_TIME_24H
            reasons.append("time_within_24h")

    if reject_penalty_applies:
        score -= WEIGHT_REJECT_PENALTY
        reasons.append("recent_user_reject")

    clamped = max(0.0, min(1.0, score))
    return DuplicateCandidateScore(
        candidate_id=candidate.id,
        score=clamped,
        reasons=tuple(reasons),
    )


def score_duplicate_candidates(
    db: Session,
    *,
    tenant_id: str,
    expense: Expense,
    candidates: Iterable[Expense],
    reject_horizon_days: int = DEFAULT_REJECT_HORIZON_DAYS,
) -> list[DuplicateCandidateScore]:
    """Score each candidate against ``expense`` and return them sorted
    by score descending.

    Caller is responsible for assembling the candidate set; today's
    ``duplicate_service`` already runs the (cheap) prefilter (image
    hash + amount/merchant/time-window). This layer adds the numeric
    ranking on top.
    """

    reject_penalty = _has_recent_reject(
        db,
        tenant_id=tenant_id,
        merchant=_normalised_merchant(expense.merchant),
        amount_cents=expense.amount_cents,
        horizon_days=reject_horizon_days,
    )
    scores = [
        _score_one_candidate(
            expense, candidate, reject_penalty_applies=reject_penalty
        )
        for candidate in candidates
        if candidate.id != expense.id
    ]
    scores.sort(key=lambda s: s.score, reverse=True)
    return scores


__all__ = [
    "ALGORITHM_VERSION",
    "DuplicateCandidateScore",
    "score_duplicate_candidates",
]
