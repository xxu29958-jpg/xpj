"""Append explicit original text through the existing expense transaction."""
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select

from app.errors import AppError
from app.models import LedgerLearningEvent, OcrFact
from app.services.file_service import _register_pil_decoders
from app.services.learning_service import EventDraft, record_event
from app.services.learning_service._algorithm_registry import ORIGINAL_TEXT_FEEDBACK
from app.services.learning_service._source_eligibility import _event_payload
from app.services.original_read_service import read_original_snapshot


def record_original_text_feedback(db, *, expense, annotations, actor_account_id):
    if not annotations:
        return
    if actor_account_id is None:
        raise AppError("permission_denied", status_code=403)
    if expense.image_deleted_at or not expense.image_path:
        raise AppError("original_feedback_source_changed", status_code=409)
    with read_original_snapshot(relative_path=expense.image_path, tenant_id=expense.tenant_id,
            expected_sha256=expense.image_hash) as original:
        if not original.verified:
            raise AppError("original_feedback_source_changed", status_code=409)
        try:
            _register_pil_decoders(original.path.suffix.lower().lstrip("."))
            with Image.open(original.path) as image:
                image.verify()
            with Image.open(original.path) as image:
                width, height = image.size
                if image.getexif().get(274) in {5, 6, 7, 8}:
                    width, height = height, width
        except (OSError, ValueError, UnidentifiedImageError) as exc:
            raise AppError("image_read_failed", status_code=422) from exc
        for annotation in annotations:
            if (annotation.image_sha256, annotation.width, annotation.height) != (original.sha256, width, height):
                raise AppError("original_feedback_source_changed", status_code=409)
            if annotation.evidence_public_id is not None and db.scalar(select(OcrFact.id).where(
                    OcrFact.tenant_id == expense.tenant_id, OcrFact.expense_id == expense.id,
                    OcrFact.public_id == annotation.evidence_public_id)) is None:
                raise AppError("original_feedback_source_changed", status_code=409)
            _append_annotation(db, expense, annotation, actor_account_id)


def _append_annotation(db, expense, annotation, actor):
    previous = db.scalars(select(LedgerLearningEvent).where(LedgerLearningEvent.tenant_id == expense.tenant_id,
        LedgerLearningEvent.subject_kind == "expense", LedgerLearningEvent.subject_id == expense.id,
        LedgerLearningEvent.actor_account_id == actor, LedgerLearningEvent.signal_type == ORIGINAL_TEXT_FEEDBACK.decision_type)
        .order_by(LedgerLearningEvent.id.desc()).limit(200))
    prior = next((row for row in previous if _event_payload(row).get("field") == annotation.field), None)
    qualified = annotation.location_state == "verified_region" and annotation.text_verified and bool(annotation.verbatim_text.strip())
    payload = {**annotation.model_dump(mode="json"), "source": "image", "original_public_id": expense.public_id,
        "intent": "original_text", "_action_outcome": "committed", "_algorithm_version": ORIGINAL_TEXT_FEEDBACK.current_version,
        "_learning_qualified": qualified, "label_usage": "visual_transcription" if qualified else "diagnostic",
        "coverage": "region" if annotation.box else "point" if annotation.point else "unlocated",
        "_qualification_reason": "已明确核对这一区域与原文" if qualified else "保留原文反馈；未同时核验精确范围与文字",
        "_feedback_revision": int(_event_payload(prior).get("_feedback_revision", 1)) + 1 if prior else 1,
        "_supersedes_event_public_id": prior.public_id if prior else None}
    event = record_event(db, EventDraft(tenant_id=expense.tenant_id, subject_kind="expense", subject_id=expense.id,
        actor_account_id=actor, event_type="edit", after_payload=payload, signal_type=ORIGINAL_TEXT_FEEDBACK.decision_type,
        signal_marker={"field": annotation.field, "image_sha256": annotation.image_sha256}))
    event.retention_days = 0
