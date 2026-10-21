"""Durable explicit OCR admission and the old ExpenseResponse completion adapter."""

from __future__ import annotations

import json
import time
from contextlib import suppress

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.errors import ERROR_MESSAGES, AppError
from app.models import ApiIdempotencyKey, BackgroundTask, Expense
from app.services import background_task_service
from app.services.background_task_admission import (
    INTERRUPTED_TASK_CODES,
    BackgroundTaskCapacityFullError,
    readmit_orphaned_task,
)
from app.services.currency_binding_service import resolve_write_capability
from app.services.expense_query import get_expense
from app.services.expense_service import _ocr
from app.services.expense_service._enrichment_receipt import require_enrichment_actor
from app.services.idempotency import (
    IdempotencyOutcomeKind,
    claim_idempotency_key,
    fingerprint_request,
    mark_idempotency_succeeded,
)
from app.services.ocr_retry_receipt import OCR_RETRY_TASK_TYPE
from app.services.session_credential_lock import lock_bootstrap_owner_transaction


def _existing_task(db: Session, claim, *, legacy: bool) -> BackgroundTask | Expense | None:
    if claim.kind == IdempotencyOutcomeKind.FINGERPRINT_MISMATCH:
        raise AppError("idempotency_key_reused", status_code=422)
    row = claim.row
    if legacy and claim.kind == IdempotencyOutcomeKind.HIT and row.resource_type == "expense":
        return get_expense(db, int(row.resource_id), row.tenant_id)
    if row.resource_type != "background_task":
        if claim.kind == IdempotencyOutcomeKind.IN_PROGRESS:
            raise AppError("idempotency_key_in_progress", status_code=409)
        return None
    task = db.scalar(select(BackgroundTask).where(BackgroundTask.public_id == row.resource_id,
        BackgroundTask.tenant_id == row.tenant_id, BackgroundTask.task_type == OCR_RETRY_TASK_TYPE))
    if task is None or str(task.source_expense_id) != row.target_id:
        raise AppError("task_not_found", status_code=404)
    # Legacy errors were never successful command acknowledgements. A later
    # retry may compute again, but cancellation and an applied receipt are final.
    if (legacy and task.status == "failed" and task.error_code not in INTERRUPTED_TASK_CODES
            and task.result_summary_json is None and task.cancellation_requested_at is None):
        return None
    return task


def _prepare_retry(db: Session, claim, *, expense_id: int, tenant_id: str,
                   initiator_account_id: int, initiator_device_id: int | None,
                   expected_row_version: int, legacy: bool):
    resolve_write_capability(db)
    expense = get_expense(db, expense_id, tenant_id)
    db.refresh(expense)
    if expense.status != "pending":
        raise AppError("expense_not_found", status_code=404)
    if expense.row_version != expected_row_version:
        raise AppError("state_conflict", status_code=409)
    if _ocr._active_provider_name() == "empty":
        raise AppError("ocr_not_configured", status_code=503)
    payload = {"expense_id": expense_id, "tenant_id": tenant_id, "timezone_name": None,
               "expected_row_version": expected_row_version, "legacy": legacy, "command_id": claim.id}
    prepared = background_task_service.prepare_enqueue(db, task_type=OCR_RETRY_TASK_TYPE,
        initiator_account_id=initiator_account_id, initiator_device_id=initiator_device_id,
        ledger_id=tenant_id, payload=payload, progress_total=1)
    prepared.task.source_expense_id = expense_id
    prepared.task.input_payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    require_enrichment_actor(db, prepared.task_id, tenant_id)
    if legacy:
        # This durable locator means accepted work, never legacy API success.
        claim.resource_type, claim.resource_id = "background_task", prepared.task_public_id
    else:
        mark_idempotency_succeeded(db, claim, resource_type="background_task", resource_id=prepared.task_public_id)
    return prepared


def _resume_retry(db: Session, task: BackgroundTask) -> BackgroundTask:
    task_id = task.id
    if task.status == "failed" and task.error_code in INTERRUPTED_TASK_CODES:
        task = readmit_orphaned_task(db, task_id) or task
    db.commit()
    if task.status == "queued":
        with suppress(background_task_service.BackgroundTaskSubmissionError):
            background_task_service.submit_existing(db, task, json.loads(task.input_payload_json))
    db.refresh(task)
    return task


def submit_expense_ocr_task(
    db: Session, *, expense_id: int, tenant_id: str, initiator_account_id: int,
    initiator_device_id: int | None, expected_row_version: int,
    request_expected_row_version: int, idempotency_key: str | None, legacy: bool = False,
) -> BackgroundTask | Expense:
    """Commit one locator before dispatch; replay the original accepted intent."""
    operation = "retry_ocr" if legacy else "retry_ocr_async"
    try:
        if not idempotency_key:
            raise AppError("idempotency_key_required", status_code=422)
        lock_bootstrap_owner_transaction(db)
        claim = claim_idempotency_key(db, tenant_id=tenant_id,
            idempotency_key=idempotency_key, operation=operation,
            target_type="expense", target_id=str(expense_id),
            request_fingerprint=fingerprint_request(operation=operation, target_id=str(expense_id),
                body={}, expected_row_version=request_expected_row_version))
        existing = _existing_task(db, claim, legacy=legacy)
        if isinstance(existing, Expense):
            return existing
        if existing is not None:
            if existing.initiated_by_account_id != initiator_account_id:
                raise AppError("permission_denied", status_code=403)
            return _resume_retry(db, existing)
        prepared = _prepare_retry(db, claim.row, expense_id=expense_id, tenant_id=tenant_id,
            initiator_account_id=initiator_account_id, initiator_device_id=initiator_device_id,
            expected_row_version=expected_row_version, legacy=legacy)
        db.commit()
        with suppress(background_task_service.BackgroundTaskSubmissionError):
            background_task_service.submit_committed(db, prepared)
        db.refresh(prepared.task)
        return prepared.task
    except BackgroundTaskCapacityFullError as exc:
        db.rollback()
        raise AppError("enrichment_capacity_full", status_code=503) from exc
    except (AppError, SQLAlchemyError):
        db.rollback()
        raise


def submit_web_expense_ocr_task(db: Session, **request) -> BackgroundTask | Expense:
    """An old browser draft can still recover its pre-async command key."""
    operation = db.scalar(select(ApiIdempotencyKey.operation).where(
        ApiIdempotencyKey.tenant_id == request["tenant_id"],
        ApiIdempotencyKey.idempotency_key == request["idempotency_key"]))
    return submit_expense_ocr_task(db, **request, legacy=operation == "retry_ocr")


def latest_expense_ocr_task(db: Session, *, tenant_id: str, expense_id: int, account_id: int) -> BackgroundTask | None:
    return db.scalar(select(BackgroundTask).where(BackgroundTask.tenant_id == tenant_id,
        BackgroundTask.source_expense_id == expense_id, BackgroundTask.initiated_by_account_id == account_id,
        BackgroundTask.task_type == OCR_RETRY_TASK_TYPE).order_by(BackgroundTask.id.desc()).limit(1))


def get_expense_ocr_task(db: Session, public_id: str, *, tenant_id: str, expense_id: int, account_id: int) -> BackgroundTask:
    task = background_task_service.get_task(db, public_id, account_id=account_id, tenant_id=tenant_id)
    if task.task_type != OCR_RETRY_TASK_TYPE or task.source_expense_id != expense_id:
        raise AppError("task_not_found", status_code=404)
    get_expense(db, expense_id, tenant_id)
    return task


def _require_legacy_completion(task: BackgroundTask) -> None:
    if task.status == "cancelled":
        raise AppError("state_conflict", "原识别请求已取消，请核对后重新发起。", status_code=409)
    if task.status == "failed":
        code = task.error_code if task.error_code in ERROR_MESSAGES else "ocr_inference_failed"
        status = {"permission_denied": 403, "state_conflict": 409, "expense_not_found": 404}.get(code, 503)
        raise AppError(code, status_code=status)
    outcome = json.loads(task.result_summary_json or "{}").get("outcome")
    if outcome not in {"updated", "no_result"}:
        raise AppError("state_conflict", status_code=409)


def wait_legacy_ocr_result(db: Session, task: BackgroundTask, *, timeout_seconds: float = 60) -> Expense:
    """Return the old completed bill response; release the DB while waiting."""
    task_id, tenant_id, expense_id = task.id, task.tenant_id, task.source_expense_id
    deadline = time.monotonic() + timeout_seconds
    db.rollback()
    while True:
        current = db.get(BackgroundTask, task_id, populate_existing=True)
        if current.status in {"completed", "failed", "cancelled"}:
            _require_legacy_completion(current)
            return get_expense(db, expense_id, tenant_id)
        db.rollback()
        if time.monotonic() >= deadline:
            raise AppError("ocr_busy", status_code=503)
        time.sleep(0.1)


def run_expense_ocr_retry_task(db: Session, task: BackgroundTask, payload: dict) -> None:
    from app.services.pending_enrichment_task_service import run_pending_expense_enrichment_task

    run_pending_expense_enrichment_task(db, task, payload, explicit_retry=True)
