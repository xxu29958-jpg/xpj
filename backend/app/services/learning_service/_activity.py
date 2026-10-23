"""Ledger-scoped, read-only evidence for the Owner's learning explanation."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AlgorithmDecision, Expense, LedgerLearningEvent, RepaymentDraft
from app.services.learning_service._source_eligibility import _event_payload, feedback_assessments


def learning_activity(db: Session, *, tenant_id: str) -> dict:
    counts = db.execute(select(AlgorithmDecision.decision_type, func.count(), func.max(AlgorithmDecision.created_at))
        .where(AlgorithmDecision.tenant_id == tenant_id).group_by(AlgorithmDecision.decision_type)).all()
    feedback = list(db.scalars(select(LedgerLearningEvent)
        .where(LedgerLearningEvent.tenant_id == tenant_id,
            LedgerLearningEvent.subject_kind.in_(("expense", "repayment_draft")),
            LedgerLearningEvent.signal_type.in_(("category_suggestion", "duplicate_candidate", "recognition_time_choice", "repayment_choice")))
        .order_by(LedgerLearningEvent.created_at.desc(), LedgerLearningEvent.id.desc()).limit(10)))
    expenses = {row.id: row for row in db.scalars(select(Expense).where(Expense.tenant_id == tenant_id,
        Expense.id.in_({row.subject_id for row in feedback if row.subject_kind == "expense"})))}
    repayments = {row.id: row for row in db.scalars(select(RepaymentDraft).where(RepaymentDraft.tenant_id == tenant_id,
        RepaymentDraft.id.in_({row.subject_id for row in feedback if row.subject_kind == "repayment_draft"})))}
    assessments = feedback_assessments(db, tenant_id=tenant_id, events=feedback)
    return {
        "usage": {kind: {"count": count, "last_at": last_at} for kind, count, last_at in counts},
        "feedback": [{"event": event, "expense": expenses.get(event.subject_id) if event.subject_kind == "expense" else None,
            "repayment": repayments.get(event.subject_id) if event.subject_kind == "repayment_draft" else None,
            "eligibility": assessments[event.id][0], "reason": assessments[event.id][1], "payload": _event_payload(event)} for event in feedback],
    }
