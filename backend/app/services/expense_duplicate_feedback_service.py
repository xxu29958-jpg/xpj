"""Bind explicit pair feedback to the same successful expense-review command."""

from __future__ import annotations

import json
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import AlgorithmDecision, Expense, LedgerLearningEvent
from app.services.learning_service import EventDraft, record_event
from app.services.learning_service._algorithm_registry import DUPLICATE_CANDIDATE, build_feedback_marker
from app.services.learning_service._source_eligibility import decision_context, source_context


def prepare_duplicate_feedback(db: Session, *, tenant_id: str, expense_id: int,
        decision_public_id: str | None, actor_account_id: int | None) -> AlgorithmDecision | None:
    # Old callers can still perform their business action, but have no evidence
    # of a displayed pair. Never recompute a new suggestion to invent that label.
    if not decision_public_id:
        return None
    decision = db.scalar(select(AlgorithmDecision).where(AlgorithmDecision.tenant_id == tenant_id,
        AlgorithmDecision.public_id == decision_public_id, AlgorithmDecision.subject_kind == "expense",
        AlgorithmDecision.subject_id == expense_id, AlgorithmDecision.decision_type == DUPLICATE_CANDIDATE.decision_type))
    if decision is None or actor_account_id is None:
        raise AppError("state_conflict", status_code=409)
    payload = json.loads(decision.output_payload)
    rows = {row.id: row for row in db.scalars(select(Expense).where(Expense.tenant_id == tenant_id,
        Expense.id.in_((expense_id, payload.get("candidate_id")))).order_by(Expense.id).with_for_update())}
    db.refresh(decision, with_for_update=True)
    current, candidate = rows.get(expense_id), rows.get(payload.get("candidate_id"))
    if (current is None or candidate is None or current.duplicate_of_id != candidate.id
            or decision.status != "active"
            or payload.get("_decision_context") != decision_context(current, decision.decision_type, actor_account_id)
            or payload.get("_candidate_context") != source_context(candidate)):
        raise AppError("state_conflict", status_code=409)
    return decision


def record_duplicate_resolution(db: Session, *, decision: AlgorithmDecision | None,
        actor_account_id: int | None, operation_key: str | None,
        resolution: Literal["keep_both", "keep_subject", "keep_candidate"]) -> None:
    if decision is None:
        return
    payload = json.loads(decision.output_payload)
    current = db.get(Expense, decision.subject_id)
    candidate = db.get(Expense, payload["candidate_id"])
    db.flush()
    db.refresh(current)
    db.refresh(candidate)
    history = db.scalars(select(LedgerLearningEvent).where(LedgerLearningEvent.tenant_id == decision.tenant_id,
        LedgerLearningEvent.subject_id == current.id, LedgerLearningEvent.subject_kind == "expense",
        LedgerLearningEvent.signal_type == decision.decision_type,
        LedgerLearningEvent.actor_account_id == actor_account_id).order_by(LedgerLearningEvent.id.desc()))
    previous = next((row for row in history if json.loads(row.after_payload or "{}").get("candidate_id") == candidate.id), None)
    same = resolution != "keep_both"
    feedback = {**payload, "_candidate_context": source_context(candidate), "_relation": "same" if same else "distinct",
        "_resolution": resolution, "_action_outcome": "committed", "_operation_key": operation_key,
        "_algorithm_version": decision.algorithm_version,
        "_feedback_revision": json.loads(previous.after_payload or "{}").get("_feedback_revision", 1) + 1 if previous else 1,
        "_supersedes_event_public_id": previous.public_id if previous else None}
    record_event(db, EventDraft(tenant_id=decision.tenant_id, decision_id=decision.id,
        event_type="accept" if same else "reject", subject_kind="expense", subject_id=current.id,
        actor_account_id=actor_account_id, before_payload=payload, after_payload=feedback,
        signal_type=decision.decision_type, signal_marker=build_feedback_marker(decision.decision_type, payload)))
    decision.status = "accepted" if same else "dismissed"
    decision.retention_days = DUPLICATE_CANDIDATE.retention_for_status(decision.status)
    decision.output_payload = json.dumps({**payload,
        "_resolved_context": decision_context(current, decision.decision_type, actor_account_id)}, ensure_ascii=False, sort_keys=True)
