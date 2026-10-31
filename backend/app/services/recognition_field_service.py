"""Trace amount/merchant choices to the original material, never to defaults."""
import json

from sqlalchemy import select

from app.models import LedgerLearningEvent
from app.schemas._recognition_fields import RecognitionFieldCandidate
from app.services.learning_service import EventDraft, read_ocr_facts, record_event
from app.services.learning_service._algorithm_registry import RECOGNITION_FIELD_CHOICE
from app.services.learning_service._source_eligibility import _event_payload
from app.services.notification_field_service import field_case_key, notification_field_sources
from app.services.recognition_amount_case import amount_case_contexts
from app.services.recognition_decision_service import bind_source_choice
from app.services.recognition_memory_service import time_candidate_key
from app.services.recognition_miss_service import miss_metadata
from app.services.recognition_presentation import source_order, verified_presentation
from app.services.recognition_source_service import candidate_source_location
from app.services.recognition_time_service import _AMOUNT_ROLES, _event_prefixes


def recognition_fields(fact) -> list[RecognitionFieldCandidate]:
    if fact is None or not fact.evidence_json:
        return []
    evidence = json.loads(fact.evidence_json).get("field_parse", {})
    events = _event_prefixes(evidence)
    candidates = evidence.get("candidates", [])
    named_merchants = {(item["value"], item.get("event_id")): item["id"]
        for item in sorted(candidates, key=lambda item: bool(item.get("event_selected")))
        if item["field"] == "merchant" and item.get("role") == "merchant"}
    selected_merchants = {named_merchants.get((item["value"], item.get("event_id")))
        for item in candidates if item["field"] == "merchant" and item.get("event_selected")}
    return [_field_candidate(fact, item, events, evidence["version"], selected_merchants) for item in candidates
        if item["field"] in {"amount_cents", "merchant"} and not (
            item["field"] == "merchant" and item.get("role") == "unknown"
            and (item["value"], item.get("event_id")) in named_merchants)]


def review_fields(fact, candidates) -> list[RecognitionFieldCandidate]:
    # Display projection only: several parse strategies can read one original
    # amount. The first listed reading stays; choices and memory still resolve
    # against the full recognition_fields list so saved draft ids keep working.
    if fact is None or not fact.evidence_json:
        return list(candidates)
    evidence = json.loads(fact.evidence_json).get("field_parse", {})
    spans = {item["id"]: item["raw_spans"] for item in evidence.get("candidates", [])}
    kept = []
    for item in candidates:
        index = next((i for i, other in enumerate(kept) if _same_reading(item, other, spans, fact.raw_text)), None)
        if index is None:
            kept.append(item)
        elif item.event_selected and not kept[index].event_selected:
            kept[index] = kept[index].model_copy(update={"event_selected": True})
    return source_order(fact, kept)


def _same_reading(item, other, spans, raw_text):
    key = ("field", "role", "value", "currency_code", "event_id", "evidence_public_id", "source")
    # Amount evidence also contains word-only role labels. Two different
    # amounts can share "支付成功"; only overlapping numeric text is a reading.
    return item.field == "amount_cents" and all(getattr(item, name) == getattr(other, name) for name in key) and any(
        any(char.isdecimal() for char in raw_text[max(left, other_left):min(end, other_end)])
        for left, end in spans.get(item.id, []) for other_left, other_end in spans.get(other.id, []))


def _field_candidate(fact, item, events, version, selected_merchants):
    field, role = item["field"], item.get("role") or "unknown"
    label = _AMOUNT_ROLES.get(role, "金额") if field == "amount_cents" else "商户"
    can_apply = role in {"payment", "expense", "total", "final_total", "rounded_total", "unknown", "merchant"}
    if field == "amount_cents":
        can_apply = can_apply and bool(item.get("currency_code"))
    source = getattr(fact, "source", "image")
    if source == "notification":
        can_apply = can_apply and not json.loads(fact.evidence_json)["input"]["truncated"]
        label = "通知 · " + label
    return RecognitionFieldCandidate(field=field, id=item["id"], value=item["value"], role=role,
        source_reading_value=item["value"],
        label=events.get(item.get("event_id"), "") + label, event_id=item.get("event_id"),
        event_selected=bool(item.get("event_selected") or item["id"] in selected_merchants) and can_apply,
        original_text="\n".join(fact.raw_text[start:end] for start, end in item["raw_spans"]),
        explanation="取自原件中这一处；请核对属于本次交易。", can_apply=can_apply,
        currency_code=item.get("currency_code"), minor_unit_exponent=item.get("minor_unit_exponent"),
        evidence_public_id=fact.public_id, parser_version=version, source=source,
        source_location=candidate_source_location(fact, item))


def field_value(expense, field, currency_code):
    if field == "merchant":
        return expense.merchant
    if expense.original_currency_code == currency_code and expense.original_amount_minor is not None:
        return expense.original_amount_minor
    return expense.amount_cents if expense.home_currency_code == currency_code else None


def _field_learning(choice, candidate, final):
    changed = final != candidate.value
    intent = "bookkeeping" if choice.intent == "candidate" and changed else choice.intent
    original_correction = intent == "original_correction" and changed and final not in (None, "")
    return {"intent": intent,
        "modified_components": [choice.field] if changed else [],
        "_learning_qualified": candidate.can_apply and (intent == "candidate" and not changed or original_correction),
        "_learning_target": "source_correction" if original_correction else "field_selection"}


def record_field_choices(db, *, expense, choices, actor_account_id):
    recorded = set()
    if not choices or actor_account_id is None:
        return recorded
    fact = read_ocr_facts(db, tenant_id=expense.tenant_id, expenses=[expense]).get(expense.id)
    notification = notification_field_sources(db, tenant_id=expense.tenant_id,
        actor_account_id=actor_account_id, expense_ids=[expense.id]).get(expense.id)
    for choice in choices:
        origin = notification if choice.source == "notification" else fact
        candidates = recognition_fields(origin)
        candidate = next((item for item in candidates if item.id == choice.candidate_id
            and item.field == choice.field and item.evidence_public_id == choice.evidence_public_id
            and item.parser_version == choice.parser_version and item.source == choice.source), None)
        if candidate is not None:
            _record_field_choice(db, expense, choice, candidate, origin, actor_account_id)
            recorded.add(choice.field)
    return recorded


def _record_field_choice(db, expense, choice, candidate, fact, actor) -> None:
    previous = db.scalars(select(LedgerLearningEvent).where(LedgerLearningEvent.tenant_id == expense.tenant_id,
        LedgerLearningEvent.subject_kind == "expense", LedgerLearningEvent.subject_id == expense.id,
        LedgerLearningEvent.actor_account_id == actor, LedgerLearningEvent.signal_type == RECOGNITION_FIELD_CHOICE.decision_type)
        .order_by(LedgerLearningEvent.id.desc()).limit(200))
    prior = next((event for event in previous if _event_payload(event).get("field") == choice.field), None)
    final = field_value(expense, choice.field, candidate.currency_code)
    raw_candidate = next(item for item in json.loads(fact.evidence_json)["field_parse"]["candidates"] if item["id"] == candidate.id)
    payload = {**choice.model_dump(), **_field_learning(choice, candidate, final),
        "selected": candidate.model_dump(exclude={"source_reading_value", "presentation"}), "final_value": final,
        "_algorithm_version": RECOGNITION_FIELD_CHOICE.current_version, "_action_outcome": "committed",
        "_case_key": field_case_key(fact), "_candidate_key": time_candidate_key(fact.raw_text, raw_candidate),
        "_amount_context": amount_case_contexts(fact).get(candidate.id) if choice.field == "amount_cents" else None,
        "_capture_context": getattr(fact, "capture_context", None),
        "_feedback_revision": int(_event_payload(prior).get("_feedback_revision", 1)) + 1 if prior else 1,
        "_supersedes_event_public_id": prior.public_id if prior else None}
    reading = ({"value": final, "currency_code": candidate.currency_code,
                "minor_unit_exponent": candidate.minor_unit_exponent} if choice.field == "amount_cents" else final)
    miss = miss_metadata(fact, choice.field, reading, payload["intent"])
    if miss is not None:
        payload["_candidate_miss"] = miss
    payload["presentation"] = verified_presentation(choice, source_order(fact, recognition_fields(fact)))
    decision_id = bind_source_choice(db, expense, actor, RECOGNITION_FIELD_CHOICE, choice, payload)
    event = record_event(db, EventDraft(tenant_id=expense.tenant_id, subject_kind="expense", subject_id=expense.id,
        decision_id=decision_id,
        actor_account_id=actor, event_type="accept" if payload["intent"] == "candidate" and payload["_learning_qualified"] else "edit",
        after_payload=payload, signal_type=RECOGNITION_FIELD_CHOICE.decision_type,
        signal_marker={"field": choice.field, "evidence_public_id": fact.public_id}))
    event.retention_days = 0
