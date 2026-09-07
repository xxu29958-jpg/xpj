from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import TYPE_CHECKING

from fastapi import Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.formparsers import MultiPartException

from app.config import get_settings
from app.errors import AppError
from app.schemas import UploadResponse
from app.services.expense_service import stage_pending_expense
from app.services.file_service import (
    SavedUpload,
    delete_relative_upload,
    read_upload_bytes,
    save_upload_bytes,
)
from app.services.idempotency import (
    IdempotencyOutcomeKind,
    claim_idempotency_key,
    fingerprint_request,
    mark_idempotency_succeeded,
)
from app.services.pending_enrichment_task_service import (
    prepare_pending_expense_enrichment,
    resume_pending_expense_enrichment,
    submit_pending_expense_enrichment,
)
from app.services.upload_receipt_service import upload_commit_is_durable
from app.upload_limits import multipart_request_limit_bytes

if TYPE_CHECKING:
    from app.models import ApiIdempotencyKey, Expense
    from app.services.background_task_service import PreparedBackgroundTask

IOS_SHORTCUT_FILE_FIELDS = ("file", "image", "photo", "screenshot")
logger = logging.getLogger("ticketbox.upload")


@dataclass(frozen=True)
class _UploadContent:
    data: bytes
    filename: str | None
    content_type: str | None


@dataclass(frozen=True)
class _UploadIntent:
    key: str
    timezone_name: str | None
    account_id: int
    device_id: int | None


async def read_raw_body_limited(
    request: Request,
    *,
    max_size_bytes: int | None = None,
) -> bytes:
    limit = get_settings().max_upload_size_bytes
    if max_size_bytes is not None:
        limit = max(0, min(limit, int(max_size_bytes)))
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise AppError("file_too_large", status_code=413)
        chunks.append(chunk)
    return b"".join(chunks)


def elapsed_ms(started_at: float) -> int:
    return max(0, int((perf_counter() - started_at) * 1000))


def pick_first_upload_file(form) -> UploadFile | None:
    """Return the first upload file using the supported capture field order."""
    for field_name in IOS_SHORTCUT_FILE_FIELDS:
        value = form.get(field_name)
        if isinstance(value, UploadFile):
            return value
    for value in form.values():
        if isinstance(value, UploadFile):
            return value
    return None


def _install_multipart_receive_limit(request: Request, *, max_body_bytes: int):
    raw_content_length = request.headers.get("content-length")
    if raw_content_length:
        try:
            declared = int(raw_content_length)
        except (TypeError, ValueError):
            declared = -1
        if declared > max_body_bytes:
            raise AppError("file_too_large", status_code=413)

    original_receive = request._receive  # noqa: SLF001 - ASGI pre-parser byte gate.
    received = 0

    async def limited_receive():
        nonlocal received
        message = await original_receive()
        if message.get("type") == "http.request":
            received += len(message.get("body") or b"")
            if received > max_body_bytes:
                # MultiPartParser owns any SpooledTemporaryFile opened so far;
                # raising its native exception makes it close those files before
                # Request.form projects the error to HTTPException.
                raise MultiPartException("Request exceeded maximum size.")
        return message

    request._receive = limited_receive  # noqa: SLF001 - restored after parsing.
    return original_receive


async def _read_request_upload(
    request: Request,
    *,
    max_size_bytes: int | None = None,
) -> tuple[_UploadContent, dict[str, int]]:
    timing_ms: dict[str, int] = {}
    limit = get_settings().max_upload_size_bytes
    if max_size_bytes is not None:
        limit = max(0, min(limit, int(max_size_bytes)))
    content_type = request.headers.get("content-type", "")
    if content_type.lower().startswith("multipart/form-data"):
        original_receive = _install_multipart_receive_limit(
            request,
            max_body_bytes=multipart_request_limit_bytes(limit),
        )
        try:
            form_context = request.form(
                max_files=4,
                max_fields=12,
                max_part_size=limit,
            )
            form_started_at = perf_counter()
            async with form_context as form:
                timing_ms["form_parse_ms"] = elapsed_ms(form_started_at)
                upload_file = pick_first_upload_file(form)
                if upload_file is not None:
                    read_started_at = perf_counter()
                    data = await read_upload_bytes(upload_file, max_size_bytes=limit)
                    timing_ms["body_read_ms"] = elapsed_ms(read_started_at)
                    return _UploadContent(data, upload_file.filename, upload_file.content_type), timing_ms
        except StarletteHTTPException as exc:
            detail = str(exc.detail).lower()
            if "maximum size" in detail or "too large" in detail:
                raise AppError("file_too_large", status_code=413) from exc
            raise AppError("invalid_request", status_code=422) from exc
        finally:
            request._receive = original_receive  # noqa: SLF001

        raise AppError("invalid_request", "表单里没有找到图片文件。", status_code=422)

    read_started_at = perf_counter()
    body = await read_raw_body_limited(request, max_size_bytes=limit)
    timing_ms["body_read_ms"] = elapsed_ms(read_started_at)
    if not body:
        raise AppError("invalid_request", status_code=422)

    return _UploadContent(body, request.headers.get("X-Upload-Filename"), content_type), timing_ms


def _save_content(
    content: _UploadContent,
    tenant_id: str,
    timing_ms: dict[str, int],
    max_size_bytes: int | None,
) -> SavedUpload:
    started_at = perf_counter()
    saved = save_upload_bytes(content.data, tenant_id=tenant_id, filename=content.filename,
        content_type=content.content_type, max_size_bytes=max_size_bytes)
    timing_ms["file_save_ms"] = elapsed_ms(started_at)
    return saved


async def save_request_upload(
    request: Request,
    tenant_id: str,
    *,
    max_size_bytes: int | None = None,
) -> tuple[SavedUpload, dict[str, int]]:
    """Preserve the file-saved / pre-commit boundary for existing consumers."""
    content, timing_ms = await _read_request_upload(request, max_size_bytes=max_size_bytes)
    return _save_content(content, tenant_id, timing_ms, max_size_bytes), timing_ms


def _upload_fingerprint(content: _UploadContent, intent: _UploadIntent) -> str:
    return fingerprint_request(
        operation="upload_screenshot", target_id=None, expected_row_version=None,
        body={
            "sha256": hashlib.sha256(content.data).hexdigest(),
            "filename": content.filename,
            "content_type": content.content_type,
            "timezone_name": intent.timezone_name,
            "account_id": intent.account_id,
            "device_id": intent.device_id,
        },
    )


async def _prepare_request_upload(
    request: Request,
    db: Session,
    tenant_id: str,
    max_size_bytes: int | None,
    intent: _UploadIntent | None,
) -> UploadResponse | tuple[SavedUpload, dict[str, int], ApiIdempotencyKey | None]:
    if intent is None:
        saved, timing = await save_request_upload(request, tenant_id, max_size_bytes=max_size_bytes)
        return saved, timing, None
    content, timing = await _read_request_upload(request, max_size_bytes=max_size_bytes)
    claim = claim_idempotency_key(
        db, tenant_id=tenant_id, idempotency_key=intent.key, operation="upload_screenshot",
        request_fingerprint=_upload_fingerprint(content, intent), target_type="upload_receipt",
    )
    if claim.kind is IdempotencyOutcomeKind.IN_PROGRESS:
        raise AppError("idempotency_key_in_progress", status_code=409)
    if claim.kind is IdempotencyOutcomeKind.FINGERPRINT_MISMATCH:
        raise AppError("idempotency_key_reused", status_code=422)
    if claim.kind is IdempotencyOutcomeKind.HIT:
        return UploadResponse.model_validate(claim.row.response_body)
    return _save_content(content, tenant_id, timing, max_size_bytes), timing, claim.row


def upload_response(
    expense: Expense,
    saved_file: SavedUpload,
    enrichment_task_public_id: str,
    duration_ms: int,
    timing_ms: dict[str, int],
) -> UploadResponse:
    return UploadResponse(
        id=expense.id,
        public_id=expense.public_id,
        enrichment_task_public_id=enrichment_task_public_id,
        status=expense.status,
        message="uploaded",
        image_hash=expense.image_hash or "",
        thumbnail_path=expense.thumbnail_path,
        duplicate_status=expense.duplicate_status,
        duplicate_of_id=expense.duplicate_of_id,
        upload_size_bytes=saved_file.size_bytes,
        duration_ms=duration_ms,
        timing_ms=dict(timing_ms),
    )


def _log_upload(
    endpoint: str,
    tenant_id: str,
    expense: Expense,
    saved_file: SavedUpload,
    timing_ms: dict[str, int],
) -> None:
    logger.info(
        "upload accepted endpoint=%s ledger=%s expense_id=%s bytes=%s media_type=%s duration_ms=%s timing_ms=%s duplicate=%s",
        endpoint, tenant_id, expense.id, saved_file.size_bytes, saved_file.media_type,
        timing_ms["total_ms"], json.dumps(timing_ms, ensure_ascii=False, sort_keys=True), expense.duplicate_status,
    )


def _commit_upload(
    db: Session,
    claim_id: int | None,
    receipt: UploadResponse | None,
    prepared_task: PreparedBackgroundTask,
) -> None:
    try:
        db.commit()
    except SQLAlchemyError:
        if claim_id is None or receipt is None:
            raise
        try:
            db.rollback()
            if upload_commit_is_durable(db, claim_id, receipt, prepared_task):
                return
        except SQLAlchemyError:
            # An unavailable read cannot prove success; preserve the commit error.
            pass
        raise


async def handle_upload(
    *,
    request: Request,
    tenant_id: str,
    db: Session,
    source: str,
    endpoint: str,
    initiator_account_id: int,
    initiator_device_id: int | None,
    timezone_name: str | None = None,
    max_size_bytes: int | None = None,
    commit_guard: Callable[[], None] | None = None,
    idempotency_key: str | None = None,
) -> UploadResponse:
    started_at = perf_counter()
    intent = (_UploadIntent(idempotency_key, timezone_name, initiator_account_id, initiator_device_id)
        if idempotency_key is not None else None)
    saved_file = None
    commit_attempted = False
    try:
        prepared_upload = await _prepare_request_upload(request, db, tenant_id, max_size_bytes, intent)
        if isinstance(prepared_upload, UploadResponse):
            resume_pending_expense_enrichment(db, task_public_id=prepared_upload.enrichment_task_public_id,
                expense_id=prepared_upload.id, tenant_id=tenant_id)
            return prepared_upload
        saved_file, timing_ms, claim = prepared_upload
        if commit_guard is not None:
            commit_guard()
        db_started_at = perf_counter()
        expense = stage_pending_expense(
            db,
            saved_file,
            tenant_id,
            source=source,
        )
        prepared_task = prepare_pending_expense_enrichment(
            db,
            expense_id=expense.id,
            tenant_id=tenant_id,
            timezone_name=timezone_name,
            expected_row_version=expense.row_version,
            initiator_account_id=initiator_account_id,
            initiator_device_id=initiator_device_id,
        )
        timing_ms["db_create_ms"] = elapsed_ms(db_started_at)
        receipt = None
        if claim is not None:
            # The accepted aggregate result must exist in the same transaction
            # as its expense and task. Later enrichment is read through task/id.
            duration_ms = elapsed_ms(started_at)
            receipt = upload_response(expense, saved_file, prepared_task.task_public_id, duration_ms,
                {**timing_ms, "total_ms": duration_ms})
            mark_idempotency_succeeded(db, claim, resource_type="upload_receipt", resource_id=expense.public_id,
                response_body=receipt.model_dump(mode="json"))
        # All deterministic writes have flushed.  From here on a raised commit
        # can mean either rollback or a lost acknowledgement, so preserve the
        # original image so a committed expense can never point at a deleted file.
        commit_attempted = True
        _commit_upload(db, claim.id if claim is not None else None, receipt, prepared_task)
    except Exception:  # noqa: BLE001 - rollback and file-compensation barrier
        db.rollback()
        if saved_file is not None and not commit_attempted:
            delete_relative_upload(saved_file.relative_path)
        raise

    enrichment_task_public_id = submit_pending_expense_enrichment(db, prepared_task)
    duration_ms = elapsed_ms(started_at)
    timing_ms["total_ms"] = duration_ms
    _log_upload(endpoint, tenant_id, expense, saved_file, timing_ms)
    return receipt or upload_response(
        expense,
        saved_file,
        enrichment_task_public_id,
        duration_ms,
        timing_ms,
    )
