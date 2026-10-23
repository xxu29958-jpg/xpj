"""Owner withdrawal appends an audit event without impersonating the original actor."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import LedgerLearningEvent
from app.services.learning_service import EventDraft, record_event
from app.services.learning_service._source_eligibility import _event_payload


def withdraw_feedback(db: Session, *, tenant_id: str, public_id: str) -> None:
    original = db.scalar(select(LedgerLearningEvent).where(LedgerLearningEvent.tenant_id == tenant_id,
        LedgerLearningEvent.public_id == public_id).with_for_update())
    if original is None or original.event_type == "withdraw":
        raise AppError("not_found", status_code=404)
    prior = db.scalars(select(LedgerLearningEvent).where(LedgerLearningEvent.tenant_id == tenant_id,
        LedgerLearningEvent.subject_id == original.subject_id, LedgerLearningEvent.event_type == "withdraw"))
    if any(_event_payload(row).get("_withdraws_event_public_id") == public_id for row in prior):
        return
    source = _event_payload(original)
    withdrawal = record_event(db, EventDraft(tenant_id=tenant_id, decision_id=original.decision_id,
        subject_kind=original.subject_kind, subject_id=original.subject_id, actor_account_id=None,
        event_type="withdraw", before_payload={"event_public_id": public_id},
        after_payload={"_withdraws_event_public_id": public_id, "_supersedes_event_public_id": public_id,
            "_feedback_revision": source.get("_feedback_revision", 1) + 1,
            "_withdrawal_authority": "local_owner", "_action_outcome": "committed",
            "candidate_id": source.get("candidate_id"), "_algorithm_version": source.get("_algorithm_version")},
        signal_type=original.signal_type, signal_marker=None))
    if original.retention_days == 0:
        withdrawal.retention_days = 0  # A retained case must not revive when its tombstone expires.
