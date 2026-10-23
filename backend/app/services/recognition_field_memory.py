"""Qualified personal cases reorder original field choices without changing facts."""
import hashlib
import json
from dataclasses import dataclass, field

from sqlalchemy import select

from app.models import AlgorithmDecision, LedgerLearningEvent
from app.services.currency_common import minor_amount_label
from app.services.learning_service._algorithm_registry import RECOGNITION_FIELD_CHOICE
from app.services.learning_service._policy import policy_enabled
from app.services.learning_service._source_eligibility import _event_payload, eligible_feedback
from app.services.recognition_decision_service import reconcile_image_decision
from app.services.recognition_memory_service import time_candidate_key, time_case_key
from app.services.time_service import now_utc


@dataclass
class FieldMemory:
    cases: list = field(default_factory=list)
    decisions: dict = field(default_factory=dict)
    new_suggestions_enabled: bool = False


def load_field_memory(db, *, tenant_id, actor_account_id, expense_ids):
    if actor_account_id is None or not expense_ids:
        return FieldMemory()
    entry = RECOGNITION_FIELD_CHOICE
    events = list(db.scalars(select(LedgerLearningEvent).where(LedgerLearningEvent.tenant_id == tenant_id,
        LedgerLearningEvent.actor_account_id == actor_account_id, LedgerLearningEvent.signal_type == entry.decision_type,
        LedgerLearningEvent.created_at <= now_utc()).order_by(LedgerLearningEvent.id.desc()).limit(200)))
    memory = FieldMemory(cases=eligible_feedback(db, tenant_id=tenant_id, events=events, actor_account_id=actor_account_id),
        new_suggestions_enabled=policy_enabled(db, tenant_id=tenant_id,
            decision_type=entry.decision_type, version=entry.current_version, axis="new_suggestions"))
    decisions = db.scalars(select(AlgorithmDecision).where(AlgorithmDecision.tenant_id == tenant_id,
        AlgorithmDecision.subject_kind == "expense", AlgorithmDecision.subject_id.in_(expense_ids),
        AlgorithmDecision.decision_type == entry.decision_type,
        AlgorithmDecision.algorithm_version == entry.current_version).order_by(AlgorithmDecision.id.desc()))
    for decision in decisions:
        memory.decisions.setdefault(decision.subject_id, []).append(decision)
    return memory


def _agreed_field(matches, fact, field_name, candidates):
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


def _corrected_field(matches, chosen):
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


def _visible_field(db, *, expense, actor, fact, field_name, chosen, matches, memory):
    entry = RECOGNITION_FIELD_CHOICE
    payload = None
    if chosen is not None:
        key = hashlib.sha256(json.dumps([actor, fact.public_id, chosen.field, chosen.id,
            sorted(row.public_id for row in matches)]).encode()).hexdigest()
        payload = {"memory_key": key, "actor_account_id": actor, "field": chosen.field,
            "candidate_id": chosen.id, "evidence_public_id": fact.public_id,
            "value": chosen.value, "selection_intent": chosen.selection_intent}
    return reconcile_image_decision(db, expense=expense, actor=actor, entry=entry, slot=field_name,
        payload=payload, previous=memory.decisions.setdefault(expense.id, []), enabled=memory.new_suggestions_enabled)


def _matching_cases(memory, expense, fact):
    case_key = time_case_key(fact)
    return [row for row in memory.cases if row.subject_id != expense.id
        and _event_payload(row).get("_case_key") == case_key
        and _event_payload(row).get("_source_context", {}).get("image_hash") != expense.image_hash]


def recall_field_choices(db, *, expense, actor_account_id, fact, candidates, memory=None):
    if actor_account_id is None or expense.status != "pending":
        return candidates
    memory = memory if memory is not None else load_field_memory(db, tenant_id=expense.tenant_id,
        actor_account_id=actor_account_id, expense_ids=[expense.id])
    matches = _matching_cases(memory, expense, fact) if fact is not None and expense.image_hash else []
    result = list(candidates)
    for field_name in ("amount_cents", "merchant"):
        field_matches = [row for row in matches if _event_payload(row).get("field") == field_name]
        chosen = _agreed_field(field_matches, fact, field_name, candidates) if fact is not None and candidates else None
        if _visible_field(db, expense=expense, actor=actor_account_id,
                fact=fact, field_name=field_name, chosen=chosen, matches=field_matches, memory=memory):
            if chosen.selection_intent == "candidate":
                chosen = chosen.model_copy(update={"explanation": chosen.explanation + " 你曾在同类原件中明确选择这一处。"})
            result = [chosen] + [item for item in result if item.id != chosen.id]
    return result
