"""Read qualified pixel transcriptions as labels, never as financial suggestions."""
import hashlib
import json
import unicodedata
from collections import Counter

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Expense, LedgerLearningEvent
from app.schemas._original_text_feedback import OriginalTextFeedback
from app.services.learning_service import read_ocr_facts
from app.services.learning_service._algorithm_registry import ORIGINAL_TEXT_FEEDBACK
from app.services.learning_service._source_eligibility import _event_payload, feedback_assessments
from app.services.original_read_service import read_original_snapshot
from app.services.recognition_source_service import original_text_lines

EVALUATOR_VERSION = "original-text-evaluation-v1"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalized(text: str) -> str:
    # Keep punctuation, case and internal whitespace: these are recognition
    # differences, not permission to replace the user's exact transcription.
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n")).strip()


def _region_text(lines, region) -> tuple[str | None, str | None]:
    left, top, right, bottom = region
    selected = []
    for line in lines:
        x1, y1, x2, y2 = line.box
        if min(right, x2) <= max(left, x1) or min(bottom, y2) <= max(top, y1):
            continue
        if not (left <= x1 < x2 <= right and top <= y1 < y2 <= bottom):
            return None, "partial_line"
        selected.append(line.text)
    return "\n".join(selected), None


def _score_label(event, expense, fact) -> dict:
    payload = _event_payload(event)
    if (payload.get("label_usage") != "visual_transcription"
            or payload.get("_algorithm_version") != ORIGINAL_TEXT_FEEDBACK.current_version):
        return {"status": "unscored", "reason": "unsupported_label_contract"}
    try:
        label = OriginalTextFeedback.model_validate({key: payload[key]
            for key in OriginalTextFeedback.model_fields if key in payload})
    except ValidationError:
        return {"status": "unscored", "reason": "invalid_label_contract"}
    if label.location_state != "verified_region" or not label.text_verified or label.image_sha256 != expense.image_hash:
        return {"status": "unscored", "reason": "unverified_label"}
    try:
        with read_original_snapshot(relative_path=expense.image_path, tenant_id=expense.tenant_id,
                expected_sha256=label.image_sha256) as original:
            if not original.verified:
                return {"status": "unscored", "reason": "unverified_original"}
    except AppError:
        return {"status": "unscored", "reason": "original_unavailable"}
    try:
        source = original_text_lines(fact, label.image_sha256)
    except (KeyError, TypeError, ValueError):
        return {"status": "unscored", "reason": "invalid_prediction_evidence"}
    if source is None or (source.width, source.height) != (label.width, label.height):
        return {"status": "unscored", "reason": "no_comparable_prediction"}
    prediction, reason = _region_text(source.lines, label.box)
    provenance = {"field": label.field, "feedback_revision": payload["_feedback_revision"],
        "image_sha256": label.image_sha256, "evidence_public_id": fact.public_id,
        "ocr_provider": fact.ocr_provider, "evidence_sha256": _digest(fact.evidence_json)}
    if reason:
        return {**provenance, "status": "unscored", "reason": reason}
    reference, prediction = _normalized(label.verbatim_text), _normalized(prediction)
    return {**provenance, "status": "scored", "exact_match": reference == prediction,
        "reference_sha256": _digest(reference), "prediction_sha256": _digest(prediction),
        "reference_characters": len(reference), "prediction_characters": len(prediction)}


def evaluate_original_text_feedback(db: Session, *, tenant_id: str, actor_account_id: int,
        event_public_ids: list[str]) -> dict:
    """Reassess one explicit cohort on each read, including every excluded row.

    The local Owner reader supplies the managed ledger and explicit person.
    Existing event, policy, source and withdrawal owners decide eligibility.
    No text, original bytes or financial values leave this evaluation response.
    """
    if not 1 <= len(event_public_ids) <= 50 or len(set(event_public_ids)) != len(event_public_ids):
        raise AppError("invalid_request", status_code=422)
    events = list(db.scalars(select(LedgerLearningEvent).where(LedgerLearningEvent.tenant_id == tenant_id,
        LedgerLearningEvent.actor_account_id == actor_account_id,
        LedgerLearningEvent.subject_kind == "expense",
        LedgerLearningEvent.signal_type == ORIGINAL_TEXT_FEEDBACK.decision_type,
        LedgerLearningEvent.public_id.in_(event_public_ids))))
    by_public_id = {event.public_id: event for event in events}
    assessments = feedback_assessments(db, tenant_id=tenant_id, events=events)
    expenses = {expense.id: expense for expense in db.scalars(select(Expense).where(
        Expense.tenant_id == tenant_id, Expense.id.in_({event.subject_id for event in events})))}
    facts = read_ocr_facts(db, tenant_id=tenant_id, expenses=expenses.values())
    rows, eligibility = [], Counter()
    for public_id in event_public_ids:
        event = by_public_id.get(public_id)
        status = assessments[event.id][0] if event is not None else "not_found"
        eligibility[status] += 1
        result = (_score_label(event, expenses[event.subject_id], facts.get(event.subject_id)) if status == "valid"
            else {"status": "ineligible", "reason": status})
        rows.append({"event_public_id": public_id, **result})
    return {"evaluator_version": EVALUATOR_VERSION, "label_version": ORIGINAL_TEXT_FEEDBACK.current_version,
        "normalization": "NFC, CRLF to LF, outer whitespace stripped; no other substitutions",
        "cohort_sha256": _digest(json.dumps([tenant_id, actor_account_id, event_public_ids], separators=(",", ":"))),
        "cohort_count": len(event_public_ids), "qualified_count": eligibility["valid"],
        "eligibility_counts": dict(eligibility), "scored_count": sum(row["status"] == "scored" for row in rows),
        "exact_match_count": sum(row.get("exact_match", False) for row in rows), "rows": rows}
