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

from app.errors import AppError
from app.models import AlgorithmDecision, Expense, LedgerLearningEvent
from app.services._json_types import JsonObject
from app.services.duplicate_service import find_duplicate_candidates
from app.services.learning_service import (
    DecisionDraft,
    EventDraft,
    compute_category_suggestion,
    record_decision,
    record_event,
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
from app.services.learning_service._policy import policy_enabled
from app.services.learning_service._source_eligibility import decision_context, source_context

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
    db: Session, *, tenant_id: str, expense: Expense, actor_account_id: int | None = None,
    merchant_scope=None,
) -> PendingSuggestions:
    if expense.status != "pending":
        return PendingSuggestions()
    return PendingSuggestions(
        category_suggestion=_category_suggestion(db, tenant_id=tenant_id, expense=expense,
            actor_account_id=actor_account_id, merchant_scope=merchant_scope),
        duplicate_candidates=duplicate_candidates_for_pending_expense(db, tenant_id=tenant_id, expense=expense, actor_account_id=actor_account_id),
    )


def record_category_choice(db: Session, *, expense: Expense, previous_category: str | None,
        previous_merchant: str | None, actor_account_id: int | None = None,
        choice: str | None = None, decision_public_id: str | None = None) -> None:
    """Remember an explicit category edit in the same successful financial transaction."""
    if actor_account_id is None or not expense.category:
        return
    if choice is None and (expense.category == previous_category or expense.merchant != previous_merchant):
        return
    decision = _active_decision(db, tenant_id=expense.tenant_id,
        decision_type=CATEGORY_SUGGESTION.decision_type, expense_id=expense.id, actor_account_id=actor_account_id)
    if choice == "suggestion" and (decision is None or decision.public_id != decision_public_id):
        return  # The saved field remains valid; stale advice is not a training label.
    if decision is not None:
        payload = _loads(decision.output_payload)
        if payload.get("merchant", expense.merchant) == expense.merchant:
            recorded = record_pending_suggestion_event(db, tenant_id=expense.tenant_id, expense_id=expense.id,
                decision_public_id=decision.public_id, actor_account_id=actor_account_id,
                event_type="accept" if payload.get("category") == expense.category else "reject",
                source_category_before=previous_category, source_was_edited=True, category_intent=choice)
            if recorded:
                return
    if choice != "suggestion":
        _record_manual_category_choice(db, expense=expense, previous_category=previous_category,
            actor_account_id=actor_account_id, category_intent=choice)


def _record_manual_category_choice(db: Session, *, expense: Expense, previous_category: str | None,
        actor_account_id: int, category_intent: str | None) -> None:
    from app.services.learning_service._category_context import category_contexts

    previous = db.scalar(select(LedgerLearningEvent).where(LedgerLearningEvent.tenant_id == expense.tenant_id,
        LedgerLearningEvent.subject_kind == "expense", LedgerLearningEvent.subject_id == expense.id,
        LedgerLearningEvent.actor_account_id == actor_account_id,
        LedgerLearningEvent.signal_type == CATEGORY_SUGGESTION.decision_type).order_by(LedgerLearningEvent.id.desc()).limit(1))
    record_event(db, EventDraft(tenant_id=expense.tenant_id, decision_id=None,
        event_type="manual_override", subject_kind="expense", subject_id=expense.id, actor_account_id=actor_account_id,
        before_payload={"category": previous_category}, after_payload={"category": expense.category,
            "_algorithm_version": "manual-choice-v2", "_category_intent": category_intent,
            "_category_context": category_contexts(db, tenant_id=expense.tenant_id, expenses=[expense])[expense.id],
            "_selected_category": expense.category, "_action_outcome": "committed",
            "_feedback_revision": int(_loads(previous.after_payload).get("_feedback_revision", 1)) + 1 if previous else 1,
            "_supersedes_event_public_id": previous.public_id if previous else None},
        signal_type=CATEGORY_SUGGESTION.decision_type,
        signal_marker=build_feedback_marker(CATEGORY_SUGGESTION.decision_type, {"category": expense.category})))


def _category_feedback_context(db, *, expense, category_intent, source_was_edited):
    from app.services.learning_service._category_context import category_contexts

    return {
        "_category_intent": category_intent or ("suggestion" if not source_was_edited else None),
        "_category_context": category_contexts(db, tenant_id=expense.tenant_id, expenses=[expense])[expense.id],
    }


def record_pending_suggestion_event(
    db: Session,
    *,
    tenant_id: str,
    expense_id: int,
    decision_public_id: str,
    event_type: str,
    actor_account_id: int | None,
    source_category_before: str | None = None,
    source_was_edited: bool = False,
    operation_key: str | None = None,
    category_intent: str | None = None,
) -> bool:
    if event_type not in {"accept", "reject"}:
        raise ValueError("unsupported pending suggestion event")

    decision = db.scalar(
        select(AlgorithmDecision)
        .where(AlgorithmDecision.tenant_id == tenant_id)
        .where(AlgorithmDecision.public_id == decision_public_id)
        .where(AlgorithmDecision.subject_kind == "expense")
        .where(AlgorithmDecision.subject_id == expense_id)
        .with_for_update()
        .limit(1)
    )
    if decision is None:
        raise ValueError("pending suggestion decision does not exist")
    recorded = _recorded_events(db, tenant_id=tenant_id, decision_id=decision.id,
        subject_kind="expense", subject_id=expense_id, actor_account_id=actor_account_id)
    if _feedback_replayed(recorded, operation_key=operation_key, event_type=event_type):
        return True
    expense = _validated_feedback_source(db, decision=decision, actor_account_id=actor_account_id,
        source_category_before=source_category_before, source_was_edited=source_was_edited)
    if expense is None:
        return False
    previous = recorded[0] if recorded else None
    if operation_key is None and previous is not None and previous.event_type == event_type:
        return True

    payload = _loads(decision.output_payload)
    marker = build_feedback_marker(decision.decision_type, payload)
    feedback = {**payload, "_algorithm_version": decision.algorithm_version,
        "_action_outcome": "committed", "_operation_key": operation_key,
        "_feedback_revision": int(_loads(previous.after_payload).get("_feedback_revision", 1)) + 1 if previous else 1,
        "_supersedes_event_public_id": previous.public_id if previous else None}
    if source_was_edited:
        feedback["_selected_category"] = expense.category
    if decision.decision_type == CATEGORY_SUGGESTION.decision_type:
        feedback.update(_category_feedback_context(db, expense=expense,
            category_intent=category_intent, source_was_edited=source_was_edited))
    if decision.decision_type == DUPLICATE_CANDIDATE.decision_type:
        feedback["_relation"] = "same" if event_type == "accept" else "distinct"
        feedback["_resolution"] = "no_financial_action"
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
            after_payload=feedback,
            signal_type=decision.decision_type,
            signal_marker=marker,
        ),
    )
    decision.output_payload = json.dumps({**payload, "_resolved_context": decision_context(expense, decision.decision_type, actor_account_id)}, ensure_ascii=False, sort_keys=True)
    _close_feedback_decision(decision, event_type)
    return True


def _close_feedback_decision(decision: AlgorithmDecision, event_type: str) -> None:
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
    # This row is locked above. An explicit new verdict can revise an earlier
    # terminal verdict; lifecycle closing intentionally only handles active rows.
    decision.status = terminal
    if target_retention is not None:
        decision.retention_days = target_retention


def _validated_feedback_source(db: Session, *, decision: AlgorithmDecision, actor_account_id: int | None,
        source_category_before: str | None, source_was_edited: bool) -> Expense | None:
    expense = db.scalar(select(Expense).where(Expense.tenant_id == decision.tenant_id, Expense.id == decision.subject_id))
    if expense is None:
        raise ValueError("pending suggestion source does not exist")
    payload = _loads(decision.output_payload)
    context = decision_context(expense, decision.decision_type, actor_account_id)
    if source_was_edited:
        context["category"] = source_category_before
        context["row_version"] = expense.row_version - 1
    if (context not in (payload.get("_decision_context"), payload.get("_resolved_context"))
            or decision.status in {"superseded", "withdrawn"}):
        # A financial edit is still valid if its old advice became stale. Do not
        # learn from that old advice; explicit feedback must reload its source.
        if source_was_edited:
            return None
        raise ValueError("建议依据已变化，请重新打开当前账目核对")
    if decision.decision_type == DUPLICATE_CANDIDATE.decision_type:
        candidate = db.scalar(select(Expense).where(Expense.tenant_id == decision.tenant_id,
            Expense.id == payload.get("candidate_id")))
        if candidate is None or payload.get("_candidate_context") != source_context(candidate):
            raise ValueError("参考账目已变化，请重新打开当前配对核对")
    return expense


def _recorded_events(
    db: Session,
    *,
    tenant_id: str,
    decision_id: int,
    subject_kind: str,
    subject_id: int,
    actor_account_id: int | None,
) -> list[LedgerLearningEvent]:
    return list(db.scalars(
        select(LedgerLearningEvent)
        .where(LedgerLearningEvent.tenant_id == tenant_id)
        .where(LedgerLearningEvent.decision_id == decision_id)
        .where(LedgerLearningEvent.subject_kind == subject_kind)
        .where(LedgerLearningEvent.subject_id == subject_id)
        .where(LedgerLearningEvent.actor_account_id == actor_account_id)
        .order_by(LedgerLearningEvent.id.desc())
    ))


def _feedback_replayed(events: list[LedgerLearningEvent], *, operation_key: str | None, event_type: str) -> bool:
    if operation_key is None:
        return False
    replay = next((event for event in events if _loads(event.after_payload).get("_operation_key") == operation_key), None)
    if replay is None:
        return False
    if replay.event_type != event_type:
        raise AppError("state_conflict", status_code=409)
    return True


def _category_suggestion(
    db: Session, *, tenant_id: str, expense: Expense, actor_account_id: int | None = None,
    merchant_scope=None,
) -> PendingCategorySuggestion | None:
    if not policy_enabled(db, tenant_id=tenant_id, decision_type=CATEGORY_SUGGESTION.decision_type,
            version=CATEGORY_SUGGESTION.current_version, axis="new_suggestions"):
        retained = _retained_decisions(db, expense=expense, actor_account_id=actor_account_id, kind=CATEGORY_SUGGESTION.decision_type)
        if not retained:
            return None
        decision, payload = retained[0]
        return PendingCategorySuggestion(decision.public_id, payload["category"], decision.score,
            payload["sample_size"], decision.algorithm_version)
    suggestion = compute_category_suggestion(
        db,
        tenant_id=tenant_id,
        merchant=expense.merchant,
        expense_id=expense.id, actor_account_id=actor_account_id, merchant_scope=merchant_scope,
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


def duplicate_candidates_for_pending_expense(
    db: Session, *, tenant_id: str, expense: Expense, actor_account_id: int | None = None
) -> list[PendingDuplicateCandidate]:
    if expense.duplicate_of_id is None:
        return []
    if not policy_enabled(db, tenant_id=tenant_id, decision_type=DUPLICATE_CANDIDATE.decision_type,
            version=DUPLICATE_CANDIDATE.current_version, axis="new_suggestions"):
        retained = _retained_decisions(db, expense=expense, actor_account_id=actor_account_id, kind=DUPLICATE_CANDIDATE.decision_type)
        return [PendingDuplicateCandidate(decision.public_id, payload["candidate_id"], payload["candidate_public_id"],
            decision.score, tuple(payload["reasons"]), decision.algorithm_version) for decision, payload in retained]
    scored = find_duplicate_candidates(db, expense)
    candidates = {row.id: row for row in db.scalars(select(Expense).where(Expense.tenant_id == tenant_id,
        Expense.id.in_([item.candidate_id for item in scored])))}
    results: list[PendingDuplicateCandidate] = []
    for item in scored:
        candidate = candidates[item.candidate_id]
        payload = {
            "candidate_id": item.candidate_id,
            "candidate_public_id": candidate.public_id,
            "_candidate_context": source_context(candidate),
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


def _retained_decisions(db: Session, *, expense: Expense, actor_account_id: int | None, kind: str) -> list[tuple[AlgorithmDecision, dict]]:
    rows = db.scalars(select(AlgorithmDecision).where(AlgorithmDecision.tenant_id == expense.tenant_id,
        AlgorithmDecision.subject_kind == "expense", AlgorithmDecision.subject_id == expense.id,
        AlgorithmDecision.decision_type == kind, AlgorithmDecision.status == "active").order_by(AlgorithmDecision.id.desc()))
    context = decision_context(expense, kind, actor_account_id)
    retained = [(row, payload) for row in rows for payload in [_loads(row.output_payload)]
        if payload.get("_decision_context") == context]
    if kind != DUPLICATE_CANDIDATE.decision_type:
        return retained
    candidates = {row.id: row for row in db.scalars(select(Expense).where(Expense.tenant_id == expense.tenant_id,
        Expense.id.in_({payload.get("candidate_id") for _, payload in retained})))}
    return [(row, payload) for row, payload in retained
        if (candidate := candidates.get(payload.get("candidate_id"))) is not None
        and payload.get("_candidate_context") == source_context(candidate)]


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
