"""Suggestion assembly for pending expense review.

This layer surfaces learning suggestions without mutating the ledger row.
It may write ``algorithm_decisions`` so the UI has a durable id to send back
when the user accepts or rejects a suggestion.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TypeAlias, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AlgorithmDecision, Expense, LedgerLearningEvent
from app.services._json_types import JsonObject
from app.services.duplicate_service import find_duplicate_candidates
from app.services.learning_service import (
    DecisionDraft,
    EventDraft,
    compute_category_suggestion,
    record_decision,
    record_event,
    set_decision_status,
    supersede_decision,
)
from app.services.learning_service._algorithm_registry import (
    CATEGORY_SUGGESTION,
    DUPLICATE_CANDIDATE,
    build_feedback_marker,
)
from app.services.learning_service._algorithm_registry import (
    get as get_algorithm_type,
)
from app.services.learning_service._source_eligibility import decision_context

DecisionPayload: TypeAlias = JsonObject


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
    db: Session, *, tenant_id: str, expense: Expense, actor_account_id: int | None = None
) -> PendingSuggestions:
    if expense.status != "pending":
        return PendingSuggestions()
    return PendingSuggestions(
        category_suggestion=_category_suggestion(db, tenant_id=tenant_id, expense=expense, actor_account_id=actor_account_id),
        duplicate_candidates=_duplicate_candidates(db, tenant_id=tenant_id, expense=expense, actor_account_id=actor_account_id),
    )


def record_category_choice(db: Session, *, expense: Expense, previous_category: str | None, previous_merchant: str | None, actor_account_id: int | None = None) -> None:
    """Remember an explicit category edit in the same successful financial transaction."""
    if expense.category == previous_category or expense.merchant != previous_merchant:
        return
    decision = _active_decision(db, tenant_id=expense.tenant_id,
        decision_type=CATEGORY_SUGGESTION.decision_type, expense_id=expense.id, actor_account_id=actor_account_id)
    if decision is not None:
        payload = _loads(decision.output_payload)
        if payload.get("merchant", expense.merchant) != expense.merchant:
            return
        record_pending_suggestion_event(db, tenant_id=expense.tenant_id, expense_id=expense.id,
            decision_public_id=decision.public_id, actor_account_id=actor_account_id,
            event_type="accept" if payload.get("category") == expense.category else "reject", source_category_before=previous_category)


def record_duplicate_choice(db: Session, *, expense: Expense, actor_account_id: int | None = None) -> None:
    """Record only the pair the command actually presented, never other recalled pairs."""
    suggestions = _duplicate_candidates(db, tenant_id=expense.tenant_id, expense=expense, actor_account_id=actor_account_id)
    for suggestion in suggestions:
        if suggestion.candidate_id != expense.duplicate_of_id:
            continue
        record_pending_suggestion_event(db, tenant_id=expense.tenant_id, expense_id=expense.id,
            decision_public_id=suggestion.decision_public_id, event_type="reject", actor_account_id=actor_account_id)


def record_pending_suggestion_event(
    db: Session,
    *,
    tenant_id: str,
    expense_id: int,
    decision_public_id: str,
    event_type: str,
    actor_account_id: int | None,
    source_category_before: str | None = None,
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
    expense = db.scalar(select(Expense).where(Expense.tenant_id == tenant_id, Expense.id == expense_id))
    if expense is None:
        raise ValueError("pending suggestion source does not exist")
    payload = _loads(decision.output_payload)
    context = decision_context(expense, decision.decision_type, actor_account_id)
    if source_category_before is not None:
        context["category"] = source_category_before
    if (context not in (payload.get("_decision_context"), payload.get("_resolved_context"))
            or decision.status == "superseded"):
        # A financial edit is still valid if its old advice became stale. Do not
        # learn from that old advice; explicit feedback must reload its source.
        if source_category_before is not None:
            return
        raise ValueError("建议依据已变化，请重新打开当前账目核对")
    if _already_recorded_event(
        db,
        tenant_id=tenant_id,
        decision_id=decision.id,
        subject_kind="expense",
        subject_id=expense_id,
        event_type=event_type, actor_account_id=actor_account_id,
    ):
        return

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
    decision.output_payload = json.dumps({**payload, "_resolved_context": decision_context(expense, decision.decision_type, actor_account_id)}, ensure_ascii=False, sort_keys=True)
    # Close the decision row to match the user's verdict. accept ->
    # 'accepted' (longer retention — positive signal worth keeping
    # for the next algorithm to learn from); reject -> 'dismissed'
    # (shorter retention — once the algorithm refreshes the
    # "user said no" trail is less useful). The per-status retention
    # comes from the algorithm-type registry, not hardcoded here.
    terminal = "accepted" if event_type == "accept" else "dismissed"
    try:
        target_retention = get_algorithm_type(
            decision.decision_type
        ).retention_for_status(terminal)
    except KeyError:
        target_retention = None  # unknown type → keep current retention
    set_decision_status(
        db,
        tenant_id=tenant_id,
        decision_id=decision.id,
        new_status=terminal,
        new_retention_days=target_retention,
    )


def _already_recorded_event(
    db: Session,
    *,
    tenant_id: str,
    decision_id: int,
    subject_kind: str,
    subject_id: int,
    event_type: str,
    actor_account_id: int | None,
) -> bool:
    existing_id = db.scalar(
        select(LedgerLearningEvent.id)
        .where(LedgerLearningEvent.tenant_id == tenant_id)
        .where(LedgerLearningEvent.decision_id == decision_id)
        .where(LedgerLearningEvent.subject_kind == subject_kind)
        .where(LedgerLearningEvent.subject_id == subject_id)
        .where(LedgerLearningEvent.event_type == event_type)
        .where(LedgerLearningEvent.actor_account_id == actor_account_id)
        .limit(1)
    )
    return existing_id is not None


def _category_suggestion(
    db: Session, *, tenant_id: str, expense: Expense, actor_account_id: int | None = None
) -> PendingCategorySuggestion | None:
    suggestion = compute_category_suggestion(
        db,
        tenant_id=tenant_id,
        merchant=expense.merchant,
        expense_id=expense.id, actor_account_id=actor_account_id,
    )
    if suggestion is None:
        return None

    payload = {
        "category": suggestion.category,
        "score": suggestion.score,
        "sample_size": suggestion.sample_size,
        "merchant": expense.merchant,
    }
    decision = _ensure_decision(
        db,
        tenant_id=tenant_id,
        expense=expense,
        decision_type=CATEGORY_SUGGESTION.decision_type,
        algorithm_version=suggestion.algorithm_version,
        payload=payload,
        score=suggestion.score, actor_account_id=actor_account_id,
    )
    if decision is None:
        return None
    return PendingCategorySuggestion(
        decision_public_id=decision.public_id,
        category=suggestion.category,
        score=suggestion.score,
        sample_size=suggestion.sample_size,
        algorithm_version=suggestion.algorithm_version,
    )


def _duplicate_candidates(
    db: Session, *, tenant_id: str, expense: Expense, actor_account_id: int | None = None
) -> list[PendingDuplicateCandidate]:
    if expense.duplicate_of_id is None:
        return []
    scored = find_duplicate_candidates(db, expense)
    candidates = {row.id: row for row in db.scalars(select(Expense).where(Expense.tenant_id == tenant_id,
        Expense.id.in_([item.candidate_id for item in scored])))}
    results: list[PendingDuplicateCandidate] = []
    for item in scored:
        candidate = candidates[item.candidate_id]
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
            score=item.score, actor_account_id=actor_account_id,
        )
        if decision is None:
            continue
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


def _active_decision(db, *, tenant_id, decision_type, expense_id, actor_account_id, candidate_id=None):
    rows = db.scalars(select(AlgorithmDecision).where(AlgorithmDecision.tenant_id == tenant_id,
        AlgorithmDecision.subject_kind == "expense", AlgorithmDecision.subject_id == expense_id,
        AlgorithmDecision.decision_type == decision_type, AlgorithmDecision.status == "active")
        .order_by(AlgorithmDecision.id.desc()))
    return next((row for row in rows if _loads(row.output_payload).get("_decision_context", {}).get("actor_account_id") == actor_account_id
        and _loads(row.output_payload).get("candidate_id") == candidate_id), None)


def _ensure_decision(
    db: Session,
    *,
    tenant_id: str,
    expense: Expense,
    decision_type: str,
    algorithm_version: str,
    payload: DecisionPayload,
    score: float | None,
    actor_account_id: int | None,
) -> AlgorithmDecision | None:
    payload = {**payload, "_decision_context": decision_context(expense, decision_type, actor_account_id)}
    closed = db.scalars(select(AlgorithmDecision).where(
        AlgorithmDecision.tenant_id == tenant_id, AlgorithmDecision.subject_kind == "expense",
        AlgorithmDecision.subject_id == expense.id, AlgorithmDecision.decision_type == decision_type,
        AlgorithmDecision.algorithm_version == algorithm_version,
        AlgorithmDecision.status.in_(("accepted", "dismissed", "withdrawn")),
    ))
    marker = build_feedback_marker(decision_type, payload)
    for row in closed:
        previous = _loads(row.output_payload)
        if (build_feedback_marker(decision_type, previous) == marker
                and previous.get("candidate_id") == payload.get("candidate_id")
                and previous.get("_resolved_context", previous.get("_decision_context")) == payload["_decision_context"]):
            return None
    existing = _active_decision(db, tenant_id=tenant_id, decision_type=decision_type,
        expense_id=expense.id, actor_account_id=actor_account_id, candidate_id=payload.get("candidate_id"))
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


def _loads(payload: str | None) -> DecisionPayload:
    if not payload:
        return {}
    loaded = json.loads(payload)
    return cast(DecisionPayload, loaded) if isinstance(loaded, dict) else {}


def _feedback_marker_payload(decision_type: str, payload: DecisionPayload) -> DecisionPayload:
    if decision_type == CATEGORY_SUGGESTION.decision_type:
        return {"category": payload.get("category")}
    if decision_type == DUPLICATE_CANDIDATE.decision_type:
        return {
            "amount_cents": payload.get("amount_cents"),
            "merchant": payload.get("merchant"),
        }
    return payload
