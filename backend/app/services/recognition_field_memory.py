"""Qualified personal cases reorder original field choices without changing facts."""
import hashlib
import json
from dataclasses import dataclass, field

from sqlalchemy import select

from app.models import AlgorithmDecision, LedgerLearningEvent
from app.schemas._recognition_fields import RecognitionFieldCandidate
from app.services.currency_common import minor_amount_label
from app.services.learning_service._algorithm_registry import RECOGNITION_FIELD_CHOICE
from app.services.learning_service._policy import policy_enabled
from app.services.learning_service._source_eligibility import _event_payload, eligible_feedback
from app.services.notification_field_service import field_case_key, notification_field_sources
from app.services.recognition_amount_case import amount_case_contexts
from app.services.recognition_decision_service import reconcile_image_decision
from app.services.recognition_field_service import recognition_fields, review_fields
from app.services.recognition_memory_service import time_candidate_key
from app.services.time_service import now_utc


@dataclass
class FieldMemory:
    cases: list = field(default_factory=list)
    decisions: dict = field(default_factory=dict)
    notification_sources: dict = field(default_factory=dict)
    new_suggestions_enabled: bool = False


def load_field_memory(db, *, tenant_id, actor_account_id, expense_ids):
    if actor_account_id is None or not expense_ids:
        return FieldMemory()
    entry = RECOGNITION_FIELD_CHOICE
    events = list(db.scalars(select(LedgerLearningEvent).where(LedgerLearningEvent.tenant_id == tenant_id,
        LedgerLearningEvent.actor_account_id == actor_account_id, LedgerLearningEvent.signal_type == entry.decision_type,
        LedgerLearningEvent.created_at <= now_utc()).order_by(LedgerLearningEvent.id.desc()).limit(200)))
    memory = FieldMemory(cases=eligible_feedback(db, tenant_id=tenant_id, events=events, actor_account_id=actor_account_id),
        notification_sources=notification_field_sources(db, tenant_id=tenant_id,
            actor_account_id=actor_account_id, expense_ids=expense_ids),
        new_suggestions_enabled=policy_enabled(db, tenant_id=tenant_id,
            decision_type=entry.decision_type, version=entry.current_version, axis="new_suggestions"))
    decisions = db.scalars(select(AlgorithmDecision).where(AlgorithmDecision.tenant_id == tenant_id,
        AlgorithmDecision.subject_kind == "expense", AlgorithmDecision.subject_id.in_(expense_ids),
        AlgorithmDecision.decision_type == entry.decision_type,
        AlgorithmDecision.algorithm_version == entry.current_version).order_by(AlgorithmDecision.id.desc()))
    for decision in decisions:
        memory.decisions.setdefault(decision.subject_id, []).append(decision)
    return memory


def _agreed_field(matches, fact, field_name, candidates) -> RecognitionFieldCandidate | None:
    keys = {json.dumps(_event_payload(row).get("_candidate_key")) for row in matches}
    if len(keys) != 1:
        return None
    key = json.loads(keys.pop())
    original = json.loads(fact.evidence_json)["field_parse"]["candidates"]
    ids = [item["id"] for item in original if item["field"] == field_name and time_candidate_key(fact.raw_text, item) == key]
    if len(ids) != 1:
        return None
    chosen = next((item for item in candidates if item.id == ids[0] and item.can_apply), None)
    return _corrected_field(matches, chosen) if chosen is not None else None


def _corrected_field(matches, chosen: RecognitionFieldCandidate) -> RecognitionFieldCandidate | None:
    payloads = [_event_payload(row) for row in matches]
    corrections = [data for data in payloads if data.get("_learning_target") == "source_correction"]
    if not corrections:
        return chosen
    # A literal correction is never a learned arithmetic transform. A different
    # value/currency or conflicting explicit interpretation keeps the baseline.
    if len(corrections) != len(payloads) or any(
            data["selected"]["value"] != chosen.value or data["selected"].get("currency_code") != chosen.currency_code
            for data in corrections):
        return None
    values = {json.dumps(data["final_value"]) for data in corrections}
    if len(values) != 1:
        return None
    value = json.loads(values.pop())
    display = minor_amount_label(value, chosen.currency_code) if chosen.field == "amount_cents" else value
    return chosen.model_copy(update={"value": value, "selection_intent": "bookkeeping",
        "explanation": f"你曾对照同类原件纠正为 {display}。请核对本张原件；原识别文字仍保留。"})


def _visible_field(db, *, expense, actor, fact, field_name, slot, chosen, matches, memory):
    entry = RECOGNITION_FIELD_CHOICE
    payload = None
    if chosen is not None:
        key = hashlib.sha256(json.dumps([actor, fact.public_id, chosen.field, chosen.id,
            sorted(row.public_id for row in matches)]).encode()).hexdigest()
        payload = {"memory_key": key, "actor_account_id": actor, "field": chosen.field,
            "slot": slot,
            "candidate_id": chosen.id, "evidence_public_id": fact.public_id,
            "value": chosen.value, "selection_intent": chosen.selection_intent}
    return reconcile_image_decision(db, expense=expense, actor=actor, entry=entry, slot=slot,
        payload=payload, previous=memory.decisions.setdefault(expense.id, []), enabled=memory.new_suggestions_enabled)


def _matching_cases(memory, expense, fact):
    case_key = field_case_key(fact)
    return [row for row in memory.cases if row.subject_id != expense.id
        and _event_payload(row).get("_case_key") == case_key
        and (_event_payload(row).get("evidence_public_id") != fact.public_id if getattr(fact, "source", "image") == "notification"
            else _event_payload(row).get("_source_context", {}).get("image_hash") != expense.image_hash)]


def _local_amount_matches(memory, expense, scopes):
    return [row for row in memory.cases if row.subject_id != expense.id
        and (data := _event_payload(row)).get("source") == "image" and data.get("field") == "amount_cents"
        and data.get("_learning_target") == "field_selection"
        and data.get("_source_context", {}).get("image_hash") != expense.image_hash
        and (data.get("_amount_context") or {}).get("scope") in scopes]


def _local_amount_case(memory, expense, fact, candidates):
    contexts = amount_case_contexts(fact) if expense.image_hash else {}
    matches = _local_amount_matches(memory, expense, {key["scope"] for key in contexts.values()})
    choices = {_event_payload(row)["_amount_context"]["choice"] for row in matches}
    ids = [identifier for identifier, key in contexts.items() if choices == {key["choice"]}]
    chosen = next((item for item in candidates if len(ids) == 1 and item.id == ids[0] and item.can_apply), None)
    return chosen, matches


def _field_choice(memory, expense, fact, candidates, matches, field_name, source):
    field_matches = [row for row in matches if _event_payload(row).get("field") == field_name]
    chosen = _agreed_field(field_matches, fact, field_name, candidates) if fact is not None and candidates else None
    if not field_matches and source == "image" and field_name == "amount_cents":
        return _local_amount_case(memory, expense, fact, candidates)
    return chosen, field_matches


def recall_field_choices(db, *, expense, actor_account_id, fact, candidates, memory=None):
    if actor_account_id is None or expense.status != "pending":
        return review_fields(fact, candidates)
    memory = memory if memory is not None else load_field_memory(db, tenant_id=expense.tenant_id,
        actor_account_id=actor_account_id, expense_ids=[expense.id])
    notification = memory.notification_sources.get(expense.id)
    return (_recall_source(db, expense, actor_account_id, fact, candidates, memory, "image")
        + _recall_source(db, expense, actor_account_id, notification, recognition_fields(notification), memory, "notification"))


def _recall_source(db, expense, actor, fact, candidates, memory, source):
    matches = _matching_cases(memory, expense, fact) if fact is not None and (source == "notification" or expense.image_hash) else []
    # Memory resolves against every reading; the displayed list may already be a projection.
    readings, result = recognition_fields(fact), list(candidates)
    for field_name in ("amount_cents", "merchant"):
        chosen, field_matches = _field_choice(memory, expense, fact, readings, matches, field_name, source)
        slot = f"notification:{field_name}" if source == "notification" else field_name
        if chosen is not None and chosen.selection_intent == "candidate":
            chosen = chosen.model_copy(update={"explanation": chosen.explanation + " 你曾在同类原件中明确选择这一处。",
                "selection_intent": "bookkeeping"})
        if _visible_field(db, expense=expense, actor=actor,
                fact=fact, field_name=field_name, slot=slot, chosen=chosen, matches=field_matches, memory=memory):
            result = [chosen] + [item for item in result if item.id != chosen.id]
    return review_fields(fact, result)
