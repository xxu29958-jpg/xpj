"""Publish the legacy command acknowledgement with its applied OCR fact."""

import json

from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import ApiIdempotencyKey, BackgroundTask
from app.services.idempotency import mark_idempotency_succeeded

OCR_RETRY_TASK_TYPE = "expense_ocr_retry"


def stage_legacy_retry_receipt(db: Session, task: BackgroundTask | None, result) -> None:
    if task is None or task.task_type != OCR_RETRY_TASK_TYPE:
        return
    payload = json.loads(task.input_payload_json)
    if not payload.get("legacy") or result.outcome not in {"updated", "no_result"}:
        return
    claim = db.get(ApiIdempotencyKey, payload["command_id"], with_for_update=True)
    if (claim is None or claim.tenant_id != task.tenant_id or claim.operation != "retry_ocr"
            or claim.target_id != str(result.expense_id)
            or (claim.resource_type, claim.resource_id) != ("background_task", task.public_id)):
        raise AppError("state_conflict", status_code=409)
    mark_idempotency_succeeded(db, claim, resource_type="expense", resource_id=str(result.expense_id))
