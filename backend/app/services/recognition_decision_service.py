"""One current, personal display decision for each original material field."""
import json

from sqlalchemy import select

from app.models import AlgorithmDecision, Expense
from app.services.learning_service import DecisionDraft, record_decision


def _owned_slot(decision, actor, slot):
    payload = json.loads(decision.output_payload)
    return payload.get("actor_account_id") == actor and payload.get("slot", payload.get("field", "expense_time")) == slot


def _retain_current_decision(owned, payload, entry):
    matching = next((row for row in owned if payload is not None and row.status != "superseded"
        and json.loads(row.output_payload).get("memory_key") == payload["memory_key"]), None)
    for row in owned:
        if row.status == "active" and row is not matching:
            row.status = "superseded"
            row.retention_days = entry.retention_for_status("superseded")
    return matching


def reconcile_image_decision(db, *, expense, actor, entry, slot, payload, previous, enabled) -> bool:
    if payload is None and not any(row.status == "active" and _owned_slot(row, actor, slot) for row in previous):
        return False
    # Refresh after this source-row lock: concurrent Web/Android readers may
    # both have loaded an empty per-response decision snapshot.
    current = db.scalar(select(Expense.id).where(Expense.tenant_id == expense.tenant_id,
        Expense.id == expense.id, Expense.status == "pending").with_for_update())
    if current is None:
        return False
    previous[:] = db.scalars(select(AlgorithmDecision).where(AlgorithmDecision.tenant_id == expense.tenant_id,
        AlgorithmDecision.subject_kind == "expense", AlgorithmDecision.subject_id == expense.id,
        AlgorithmDecision.decision_type == entry.decision_type,
        AlgorithmDecision.algorithm_version == entry.current_version)
        .order_by(AlgorithmDecision.id.desc()).execution_options(populate_existing=True)).all()
    owned = [row for row in previous if _owned_slot(row, actor, slot)]
    matching = _retain_current_decision(owned, payload, entry)
    if matching is not None:
        return matching.status == "active"
    if payload is None or not enabled:
        return False
    decision = record_decision(db, DecisionDraft(tenant_id=expense.tenant_id, subject_kind="expense", subject_id=expense.id,
        subject_public_id=expense.public_id, decision_type=entry.decision_type, algorithm_version=entry.current_version,
        payload=payload))
    previous.insert(0, decision)
    return True
