"""One current, personal display decision for each original material field."""
import json

from sqlalchemy import String, case, cast, func, select
from sqlalchemy.dialects.postgresql import JSONB

from app.models import AlgorithmDecision, Expense, LedgerLearningEvent
from app.services.learning_service import DecisionDraft, record_decision
from app.services.time_service import now_utc


def _json_payload(column):
    return cast(case((func.pg_input_is_valid(column, "jsonb"), column), else_="{}"), JSONB)


def source_learning_window_predicate():
    """Diagnostics remain auditable without occupying the bounded learning window."""
    return _json_payload(LedgerLearningEvent.after_payload)["_learning_target"].astext.is_distinct_from("candidate_miss")


def _source_choice_decision(db, expense, actor, entry, choice):
    """A remembered suggestion is not an independent source annotation, even on an old client."""
    return _source_exposure_decision(db, expense, actor, entry, choice, match_candidate=True)


def _source_exposure_decision(db, expense, actor, entry, choice, *, match_candidate=False):
    payload = _json_payload(AlgorithmDecision.output_payload)
    return db.scalar(select(AlgorithmDecision).where(AlgorithmDecision.tenant_id == expense.tenant_id,
        AlgorithmDecision.subject_kind == "expense", AlgorithmDecision.subject_id == expense.id,
        AlgorithmDecision.decision_type == entry.decision_type, AlgorithmDecision.created_at <= now_utc(),
        payload["actor_account_id"].astext == str(actor),
        payload["field"].astext == getattr(choice, "field", "expense_time"),
        payload["evidence_public_id"].astext == choice.evidence_public_id,
        payload["candidate_id"].astext == choice.candidate_id if match_candidate else True)
        .order_by(AlgorithmDecision.id.desc()).limit(1))


def bind_source_choice(db, expense, actor, entry, choice, payload):
    decision = _source_choice_decision(db, expense, actor, entry, choice)
    exposure = decision or _source_exposure_decision(db, expense, actor, entry, choice)
    payload["_history_exposed"] = exposure is not None
    if decision is not None and payload["intent"] == "candidate":
        payload.update(intent="bookkeeping", _learning_qualified=False, _adopted_suggestion_public_id=decision.public_id)
    return decision.id if decision is not None else None


def recognition_adoption_predicates():
    """Match historical exposure before feedback without rewriting old events."""
    event = _json_payload(LedgerLearningEvent.after_payload)
    decision = _json_payload(AlgorithmDecision.output_payload)
    return (LedgerLearningEvent.tenant_id == AlgorithmDecision.tenant_id,
        LedgerLearningEvent.subject_kind == "expense", AlgorithmDecision.subject_kind == "expense",
        LedgerLearningEvent.subject_id == AlgorithmDecision.subject_id,
        LedgerLearningEvent.signal_type == AlgorithmDecision.decision_type,
        LedgerLearningEvent.signal_type.in_(("recognition_field_choice", "recognition_time_choice")),
        AlgorithmDecision.created_at <= LedgerLearningEvent.created_at,
        event["intent"].astext == "candidate",
        decision["actor_account_id"].astext == cast(LedgerLearningEvent.actor_account_id, String),
        event["field"] == decision["field"], event["candidate_id"] == decision["candidate_id"],
        event["evidence_public_id"] == decision["evidence_public_id"])


def recognition_adoption_ids(db, tenant_id, events):
    identifiers = {row.id for row in events if row.signal_type in {"recognition_field_choice", "recognition_time_choice"}}
    if not identifiers:
        return set()
    return set(db.scalars(select(LedgerLearningEvent.id).where(LedgerLearningEvent.tenant_id == tenant_id,
        LedgerLearningEvent.id.in_(identifiers), select(AlgorithmDecision.id)
        .where(*recognition_adoption_predicates()).correlate(LedgerLearningEvent).exists())))


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
