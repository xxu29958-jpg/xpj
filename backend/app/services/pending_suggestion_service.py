"""Suggestion assembly for pending expense review.

This layer surfaces learning suggestions without mutating the ledger row.
It may write ``algorithm_decisions`` so the UI has a durable id to send back
when the user accepts or rejects a suggestion.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AlgorithmDecision, Expense
from app.services.learning_service import (
    DecisionDraft,
    EventDraft,
    active_decision_for_subject,
    compute_category_suggestion,
    record_decision,
    record_event,
    score_duplicate_candidates,
    set_decision_status,
    supersede_decision,
)
from app.services.learning_service._algorithm_registry import (
    CATEGORY_SUGGESTION,
    DUPLICATE_CANDIDATE,
    build_feedback_marker,
)


@dataclass(frozen=True)
class PendingCategorySuggestion:
    decision_public_id: str
    category: str
    score: float
    sample_size: int
    algorithm_version: str


@dataclass(frozen=True)
class PendingDuplicateCandidate:
    decision_public_id: str
    candidate_id: int
    candidate_public_id: str | None
    score: float
    reasons: tuple[str, ...] = field(default_factory=tuple)
    algorithm_version: str = ""


@dataclass(frozen=True)
class PendingSuggestions:
    category_suggestion: PendingCategorySuggestion | None = None
    duplicate_candidates: list[PendingDuplicateCandidate] = field(default_factory=list)


def suggestions_for_pending_expense(
    db: Session, *, tenant_id: str, expense: Expense
) -> PendingSuggestions:
    return PendingSuggestions(
        category_suggestion=_category_suggestion(db, tenant_id=tenant_id, expense=expense),
        duplicate_candidates=_duplicate_candidates(db, tenant_id=tenant_id, expense=expense),
    )


def record_pending_suggestion_event(
    db: Session,
    *,
    tenant_id: str,
    expense_id: int,
    decision_public_id: str,
    event_type: str,
    actor_account_id: int | None,
) -> None:
    if event_type not in {"accept", "reject"}:
        raise ValueError("unsupported pending suggestion event")

    decision = db.scalar(
        select(AlgorithmDecision)
        .where(AlgorithmDecision.tenant_id == tenant_id)
        .where(AlgorithmDecision.public_id == decision_public_id)
        .where(AlgorithmDecision.subject_kind == "expense")
        .where(AlgorithmDecision.subject_id == expense_id)
        .limit(1)
    )
    if decision is None:
        raise ValueError("pending suggestion decision does not exist")

    payload = _loads(decision.output_payload)
    marker = build_feedback_marker(decision.decision_type, payload)
    record_event(
        db,
        EventDraft(
            tenant_id=tenant_id,
            decision_id=decision.id,
            event_type=event_type,
            subject_kind="expense",
            subject_id=expense_id,
            actor_account_id=actor_account_id,
            before_payload=_feedback_marker_payload(decision.decision_type, payload),
            after_payload=payload,
            signal_type=decision.decision_type,
            signal_marker=marker,
        ),
    )
    # Close the decision row to match the user's verdict. accept ->
    # 'accepted', reject -> 'dismissed'. The UI must not show the same
    # suggestion again on this subject; the cleanup story (per-row
    # retention) eventually harvests the closed row.
    terminal = "accepted" if event_type == "accept" else "dismissed"
    set_decision_status(
        db,
        tenant_id=tenant_id,
        decision_id=decision.id,
        new_status=terminal,
    )


def _category_suggestion(
    db: Session, *, tenant_id: str, expense: Expense
) -> PendingCategorySuggestion | None:
    suggestion = compute_category_suggestion(
        db,
        tenant_id=tenant_id,
        merchant=expense.merchant,
        expense_id=expense.id,
    )
    if suggestion is None:
        return None

    payload = {
        "category": suggestion.category,
        "score": suggestion.score,
        "sample_size": suggestion.sample_size,
    }
    decision = _ensure_decision(
        db,
        tenant_id=tenant_id,
        expense=expense,
        decision_type=CATEGORY_SUGGESTION.decision_type,
        algorithm_version=suggestion.algorithm_version,
        payload=payload,
        score=suggestion.score,
    )
    return PendingCategorySuggestion(
        decision_public_id=decision.public_id,
        category=suggestion.category,
        score=suggestion.score,
        sample_size=suggestion.sample_size,
        algorithm_version=suggestion.algorithm_version,
    )


def _duplicate_candidates(
    db: Session, *, tenant_id: str, expense: Expense
) -> list[PendingDuplicateCandidate]:
    if expense.duplicate_of_id is None:
        return []
    candidate = db.scalar(
        select(Expense)
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.id == expense.duplicate_of_id)
        .limit(1)
    )
    if candidate is None:
        return []
    scored = score_duplicate_candidates(
        db, tenant_id=tenant_id, expense=expense, candidates=[candidate]
    )
    results: list[PendingDuplicateCandidate] = []
    for item in scored:
        if item.score <= 0:
            continue
        payload = {
            "candidate_id": item.candidate_id,
            "candidate_public_id": candidate.public_id,
            "score": item.score,
            "reasons": list(item.reasons),
            "amount_cents": expense.amount_cents,
            "merchant": (expense.merchant or "").strip().casefold(),
        }
        decision = _ensure_decision(
            db,
            tenant_id=tenant_id,
            expense=expense,
            decision_type=DUPLICATE_CANDIDATE.decision_type,
            algorithm_version=item.algorithm_version,
            payload=payload,
            score=item.score,
        )
        results.append(
            PendingDuplicateCandidate(
                decision_public_id=decision.public_id,
                candidate_id=item.candidate_id,
                candidate_public_id=candidate.public_id,
                score=item.score,
                reasons=item.reasons,
                algorithm_version=item.algorithm_version,
            )
        )
    return results


def _ensure_decision(
    db: Session,
    *,
    tenant_id: str,
    expense: Expense,
    decision_type: str,
    algorithm_version: str,
    payload: dict[str, Any],
    score: float | None,
) -> AlgorithmDecision:
    existing = active_decision_for_subject(
        db,
        tenant_id=tenant_id,
        decision_type=decision_type,
        subject_kind="expense",
        subject_id=expense.id,
    )
    if (
        existing is not None
        and existing.algorithm_version == algorithm_version
        and _loads(existing.output_payload) == payload
    ):
        return existing

    decision = record_decision(
        db,
        DecisionDraft(
            tenant_id=tenant_id,
            decision_type=decision_type,
            algorithm_version=algorithm_version,
            subject_kind="expense",
            subject_id=expense.id,
            subject_public_id=expense.public_id,
            score=score,
            payload=payload,
        ),
    )
    if existing is not None:
        supersede_decision(
            db,
            tenant_id=tenant_id,
            old_decision_id=existing.id,
            new_decision_id=decision.id,
        )
    return decision


def _loads(payload: str | None) -> dict[str, Any]:
    if not payload:
        return {}
    loaded = json.loads(payload)
    return loaded if isinstance(loaded, dict) else {}


def _feedback_marker_payload(
    decision_type: str, payload: dict[str, Any]
) -> dict[str, Any]:
    if decision_type == CATEGORY_SUGGESTION.decision_type:
        return {"category": payload.get("category")}
    if decision_type == DUPLICATE_CANDIDATE.decision_type:
        return {
            "amount_cents": payload.get("amount_cents"),
            "merchant": payload.get("merchant"),
        }
    return payload
