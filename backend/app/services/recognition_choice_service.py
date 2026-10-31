"""Attribute a deliberate source choice only after its ordinary save succeeds."""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Expense, LedgerLearningEvent
from app.schemas._recognition_choice import RecognitionTimeChoice
from app.services.learning_service import EventDraft, read_ocr_facts, record_event
from app.services.learning_service._algorithm_registry import RECOGNITION_TIME_CHOICE
from app.services.learning_service._source_eligibility import _event_payload
from app.services.notification_time_memory import notification_time_choice_context, notification_time_sources
from app.services.notification_time_service import notification_time
from app.services.recognition_decision_service import bind_source_choice
from app.services.recognition_time_service import recognition_time
from app.services.recognition_time_values import candidate_components as _candidate_components
from app.services.recognition_time_values import time_components


def _chosen_source(db: Session, expense: Expense, choice: RecognitionTimeChoice, actor_account_id: int):
    fact = read_ocr_facts(db, tenant_id=expense.tenant_id, expenses=[expense]).get(expense.id)
    capture = notification_time_sources(db, tenant_id=expense.tenant_id,
        actor_account_id=actor_account_id, expense_ids=[expense.id]).get(expense.id)
    notification = notification_time(capture) if capture else None
    evidence = recognition_time(fact, notification=notification)
    candidate = next((item for item in evidence.candidates if item.id == choice.candidate_id
        and item.evidence_public_id == choice.evidence_public_id and item.parser_version == choice.parser_version
        and item.source == choice.source), None) if evidence else None
    return fact, candidate, capture


def record_time_choice(db: Session, *, expense: Expense, choice: RecognitionTimeChoice | None,
        actor_account_id: int | None) -> bool:
    if choice is None or actor_account_id is None:
        return False
    fact, candidate, capture = _chosen_source(db, expense, choice, actor_account_id)
    if candidate is None:
        return False  # Saving valid accounting intent must not manufacture a stale/foreign label.
    previous = db.scalar(select(LedgerLearningEvent).where(LedgerLearningEvent.tenant_id == expense.tenant_id,
        LedgerLearningEvent.subject_kind == "expense", LedgerLearningEvent.subject_id == expense.id,
        LedgerLearningEvent.actor_account_id == actor_account_id,
        LedgerLearningEvent.signal_type == RECOGNITION_TIME_CHOICE.decision_type)
        .order_by(LedgerLearningEvent.id.desc()).limit(1))
    payload = {**_choice_components_payload(expense, choice, candidate),
        "_feedback_revision": int(_event_payload(previous).get("_feedback_revision", 1)) + 1 if previous else 1,
        "_supersedes_event_public_id": previous.public_id if previous else None}
    if choice.source == "image" and fact is not None:
        from app.services.recognition_memory_service import time_candidate_key, time_case_key

        payload["_case_key"] = time_case_key(fact)
        field_parse = json.loads(fact.evidence_json)["field_parse"]
        payload["_candidate_key"] = next(time_candidate_key(fact.raw_text, item) for item in field_parse["candidates"]
            if item["id"] == choice.candidate_id)
        from app.services.recognition_miss_service import miss_metadata

        miss = miss_metadata(fact, "expense_time", payload["final_components"], payload["intent"])
        if miss is not None:
            payload["_candidate_miss"] = miss
    elif choice.source == "notification" and capture is not None:
        payload.update(notification_time_choice_context(capture, choice.candidate_id))
    decision_id = bind_source_choice(db, expense, actor_account_id, RECOGNITION_TIME_CHOICE, choice, payload)
    event = record_event(db, EventDraft(tenant_id=expense.tenant_id, subject_kind="expense", subject_id=expense.id,
        decision_id=decision_id,
        actor_account_id=actor_account_id, event_type="accept" if payload["_learning_qualified"] else "edit",
        after_payload=payload, signal_type=RECOGNITION_TIME_CHOICE.decision_type,
        signal_marker={"field": "expense_time", "evidence_public_id": choice.evidence_public_id}))
    event.retention_days = 0  # Explicit cases live until withdrawn/invalidated, independently of short diagnostic logs.
    return True


def _choice_components_payload(expense: Expense, choice: RecognitionTimeChoice, candidate) -> dict:
    selected, final = _candidate_components(candidate), time_components(expense)
    changed = [key for key in selected if selected[key] != final.get(key)]
    intent = choice.intent if choice.intent != "candidate" or not changed else "bookkeeping"
    return {**choice.model_dump(), "intent": intent, "field": "expense_time",
        "selected": candidate.model_dump(), "final_components": final, "modified_components": changed,
        "_algorithm_version": RECOGNITION_TIME_CHOICE.current_version, "_action_outcome": "committed",
        "_learning_qualified": intent == "candidate" and bool(selected) and candidate.can_apply and not changed}
