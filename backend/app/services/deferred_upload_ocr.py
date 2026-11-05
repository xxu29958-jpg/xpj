"""Admit skipped receipt images to the existing upload OCR queue."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import aliased

from app.config import get_settings
from app.database import SessionLocal
from app.errors import AppError
from app.models import BackgroundTask, Expense, OcrFact
from app.services.background_task_handler_api import OCR_TASK_TYPES
from app.services.ocr_execution_context import upload_result_with_notice
from app.services.pending_enrichment_task_service import (
    PENDING_EXPENSE_ENRICHMENT_TASK_TYPE,
    prepare_pending_expense_enrichment,
)
from app.services.session_credential_lock import lock_bootstrap_owner_transaction


def _pending_uploads():
    later = aliased(BackgroundTask)
    return (
        select(BackgroundTask.id)
        .join(Expense, Expense.id == BackgroundTask.source_expense_id)
        .where(
            Expense.tenant_id == BackgroundTask.tenant_id,
            Expense.status == "pending", Expense.image_path.is_not(None), Expense.image_deleted_at.is_(None),
            BackgroundTask.task_type == PENDING_EXPENSE_ENRICHMENT_TASK_TYPE,
            BackgroundTask.status == "completed", BackgroundTask.result_summary_json.is_not(None),
            BackgroundTask.initiated_by_account_id.is_not(None),
            ~select(OcrFact.id).where(OcrFact.tenant_id == Expense.tenant_id, OcrFact.expense_id == Expense.id).exists(),
            ~select(later.id).where(
                later.tenant_id == Expense.tenant_id, later.source_expense_id == Expense.id,
                later.task_type.in_(OCR_TASK_TYPES), later.id > BackgroundTask.id,
            ).exists(),
        )
    )


def _queue_skipped_upload(task_id: int) -> None:
    with SessionLocal.begin() as db:
        # Explicit retries use this same lock. Re-read after acquiring it so
        # competing scans cannot both admit another task for the same upload.
        lock_bootstrap_owner_transaction(db)
        row = db.execute(_pending_uploads().where(BackgroundTask.id == task_id)
                         .with_only_columns(BackgroundTask, Expense.row_version)).one_or_none()
        if row is None:
            return
        task, version = row
        try:
            summary = json.loads(task.result_summary_json)
            original = json.loads(task.input_payload_json or "{}")
        except (ValueError, TypeError):
            return
        if (not isinstance(summary, dict) or summary.get("outcome") not in ("updated", "no_result")
                or summary.get("ocr_attempts") or not isinstance(original, dict)):
            return
        # Current receipts and 1.2.0 execution records can positively identify
        # a disabled run. Older receipts without either signal are ambiguous.
        if upload_result_with_notice(summary, task.execution_context_json).get("ocr_notice") != "auto_ocr_disabled":
            return
        if (original.get("expense_id") != task.source_expense_id or original.get("tenant_id") != task.tenant_id
                or not isinstance(original.get("timezone_name"), (str, type(None)))):
            return
        prepare_pending_expense_enrichment(
            db, expense_id=task.source_expense_id, tenant_id=task.tenant_id,
            timezone_name=original.get("timezone_name"), expected_row_version=version,
            initiator_account_id=task.initiated_by_account_id, initiator_device_id=task.initiated_by_device_id,
        )
        # The normal recovery worker dispatches committed queued tasks, also
        # after a restart. The accepted upload and its receipt stay replayable.


def queue_skipped_uploads(after_id: int, *, limit: int = 8) -> int:
    """Visit a bounded page. Cycle past busy ledgers and revisit them next pass."""
    settings = get_settings()
    if not settings.ocr_auto_run or settings.ocr_provider == "empty":
        return 0
    with SessionLocal() as db:
        ids = list(db.scalars(_pending_uploads().where(BackgroundTask.id > after_id)
                              .order_by(BackgroundTask.id).limit(limit)))
    for task_id in ids:
        try:
            _queue_skipped_upload(task_id)
        except AppError as exc:
            if exc.error not in {"enrichment_capacity_full", "upload_storage_full"}:
                raise
    return ids[-1] if len(ids) == limit else 0
