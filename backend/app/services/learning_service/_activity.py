"""Ledger-scoped, read-only evidence for the Owner's learning explanation."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AlgorithmDecision, Expense, LedgerLearningEvent


def learning_activity(db: Session, *, tenant_id: str) -> dict:
    counts = db.execute(select(AlgorithmDecision.decision_type, func.count(), func.max(AlgorithmDecision.created_at))
        .where(AlgorithmDecision.tenant_id == tenant_id).group_by(AlgorithmDecision.decision_type)).all()
    feedback = db.execute(select(LedgerLearningEvent, Expense)
        .join(Expense, Expense.id == LedgerLearningEvent.subject_id)
        .where(LedgerLearningEvent.tenant_id == tenant_id, Expense.tenant_id == tenant_id,
            LedgerLearningEvent.subject_kind == "expense",
            LedgerLearningEvent.signal_type.in_(("category_suggestion", "duplicate_candidate")))
        .order_by(LedgerLearningEvent.created_at.desc(), LedgerLearningEvent.id.desc()).limit(10)).all()
    return {
        "usage": {kind: {"count": count, "last_at": last_at} for kind, count, last_at in counts},
        "feedback": [{"event": event, "expense": expense} for event, expense in feedback],
    }
