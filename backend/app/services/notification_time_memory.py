"""Personal time-role cases bound to the original notification and its current link."""
import hashlib
import json
import re

from sqlalchemy import select

from app.models import Expense, PaymentCapture
from app.schemas._recognition_time import RecognitionTimeCandidate
from app.services.learning_service._algorithm_registry import RECOGNITION_TIME_CHOICE
from app.services.learning_service._source_eligibility import _event_payload
from app.services.recognition_decision_service import reconcile_image_decision
from app.services.recognition_evidence_context import (
    capture_evidence_complete,
    capture_evidence_context,
    time_candidate_key,
)
from app.services.recognition_time_service import rank_time_origin


def notification_time_sources(db, *, tenant_id, actor_account_id, expense_ids):
    if actor_account_id is None or not expense_ids:
        return {}
    rows = db.execute(select(Expense.id, PaymentCapture).join(PaymentCapture,
        PaymentCapture.expense_public_id == Expense.public_id).where(Expense.tenant_id == tenant_id,
        Expense.id.in_(expense_ids), PaymentCapture.tenant_id == tenant_id,
        PaymentCapture.actor_account_id == actor_account_id, PaymentCapture.kind == "expense"))
    return {expense_id: capture for expense_id, capture in rows if capture.time_evidence}


def _case_key(capture):
    frozen = capture.time_evidence
    parts = ["notification-time", capture.source, frozen.get("capture_parser_version", capture.parser_version), frozen["field_parse"]["version"],
        frozen["input"]["source_timezone"], frozen["input"]["truncated"],
        [item["field"] for item in frozen["input"]["fragments"]], re.sub(r"\d+", "#", frozen["raw_text"])]
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


def notification_time_choice_context(capture, candidate_id):
    frozen = capture.time_evidence
    original = next(item for item in frozen["field_parse"]["candidates"] if item["id"] == candidate_id)
    return {"_case_key": _case_key(capture), "_candidate_key": time_candidate_key(frozen["raw_text"], original),
        "_capture_context": capture_evidence_context(capture, kind="time"),
        **({"_learning_qualified": False} if not capture_evidence_complete(capture, kind="time") else {})}


def _agreed_time(capture, response, matches) -> RecognitionTimeCandidate | None:
    if not capture_evidence_complete(capture, kind="time"):
        return None
    keys = {json.dumps(_event_payload(row).get("_candidate_key")) for row in matches}
    candidates = [item for item in response.candidates if item.source == "notification"
        and item.evidence_public_id == capture.public_id] if response else []
    if len(keys) != 1 or len(candidates) < 2:
        return None
    key, frozen = json.loads(keys.pop()), capture.time_evidence
    ids = [item["id"] for item in frozen["field_parse"]["candidates"]
        if time_candidate_key(frozen["raw_text"], item) == key]
    if len(ids) != 1:
        return None
    return next((item for item in candidates if item.id == ids[0] and item.can_apply), None)


def recall_notification_time(db, *, expense, actor, response, memory):
    capture = memory.notification_sources.get(expense.id)
    case_key = _case_key(capture) if capture else None
    matches = [row for row in memory.cases if row.subject_id != expense.id
        and _event_payload(row).get("_case_key") == case_key] if capture else []
    chosen = _agreed_time(capture, response, matches) if capture else None
    payload = None
    if chosen is not None:
        key = hashlib.sha256(json.dumps([actor, capture.public_id, chosen.id,
            sorted(row.public_id for row in matches)]).encode()).hexdigest()
        payload = {"memory_key": key, "actor_account_id": actor, "field": "expense_time",
            "slot": "notification:expense_time", "evidence_public_id": capture.public_id, "candidate_id": chosen.id}
    visible = reconcile_image_decision(db, expense=expense, actor=actor, entry=RECOGNITION_TIME_CHOICE,
        slot="notification:expense_time", payload=payload, previous=memory.decisions.setdefault(expense.id, []),
        enabled=memory.new_suggestions_enabled)
    if not visible:
        return response
    return rank_time_origin(response, chosen.model_copy(update={
        "explanation": chosen.explanation + " 你曾在同类通知中明确选择这一处时间。"}))
