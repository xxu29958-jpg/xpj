"""Durable, per-expense cleanup of frozen attachment references."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.attachment_cleanup_contract import CleanupFile, CleanupRequest
from app.config import get_settings
from app.errors import AppError
from app.models import Expense, LedgerAuditLog
from app.services.currency_binding_service import authorize_currency_metadata_write
from app.services.file_service import resolve_upload_path_for_tenant
from app.services.optimistic_concurrency import bump_row_version
from app.services.time_service import now_utc

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CleanupSettlement:
    changed: bool = False
    deleted_images: int = 0
    deleted_thumbnails: int = 0
    pending: bool = False


def read_cleanup_request(expense: Expense) -> CleanupRequest | None:
    """Parse only for attachment work; ordinary financial reads need not parse it."""
    raw = expense.attachment_cleanup_request
    if raw is None:
        return None
    try:
        return CleanupRequest.model_validate(raw)
    except ValidationError as exc:
        raise AppError("attachment_cleanup_invalid", status_code=409) from exc


def cleanup_request_covers_source(expense: Expense, source_reference: str | None = None) -> bool:
    source = expense.image_path if source_reference is None else source_reference
    request = read_cleanup_request(expense)
    return bool(source and request and request.image and request.image.reference == source
                and any(item and item.outcome == "pending" for item in (request.image, request.thumbnail)))


def pending_cleanup_references(raw: dict | None) -> tuple[str, ...]:
    """Protect old paths still owned by an unresolved request from orphan GC."""
    if raw is None:
        return ()
    try:
        request = CleanupRequest.model_validate(raw)
    except ValidationError as exc:
        raise AppError("attachment_cleanup_invalid", status_code=409) from exc
    return tuple(item.reference for item in (request.image, request.thumbnail) if item and item.outcome == "pending")


def cleanup_policy_enabled(request: CleanupRequest, settings) -> bool:
    return {
        "after_confirm": settings.delete_image_after_confirm,
        "confirmed_retention": settings.delete_image_after_days > 0,
        "rejected_retention": settings.delete_rejected_after_days > 0,
    }[request.reason]


def _log_missing_reference(reference: str, tenant_id: str) -> None:
    digest = hashlib.sha256(f"{tenant_id}\0{reference}".encode()).hexdigest()[:16]
    logger.error("event=upload_integrity_missing reference_digest=%s referenced upload is missing; "
                 "database deletion marker remains unset", digest,
                 extra={"event": "upload_integrity_missing", "reference_digest": digest})


def _new_request(expense: Expense, reason: str) -> CleanupRequest | None:
    files = {}
    for kind, reference, deleted_at in (
        ("image", expense.image_path, expense.image_deleted_at),
        ("thumbnail", expense.thumbnail_path, expense.thumbnail_deleted_at),
    ):
        if reference is None or deleted_at is not None:
            continue
        candidate = resolve_upload_path_for_tenant(reference, expense.tenant_id)
        if candidate is None:
            return None
        try:
            if not candidate.exists():
                _log_missing_reference(reference, expense.tenant_id)
                return None
            if not candidate.is_file():
                return None
        except OSError:
            return None
        files[kind] = CleanupFile(reference=reference)
    if not files:
        return None
    return CleanupRequest(request_id=uuid4(), reason=reason, requested_at=now_utc(), **files)


def _retention_due(expense: Expense, reason: str, settings) -> bool:
    if reason == "after_confirm":
        return settings.delete_image_after_confirm
    status = "confirmed" if reason == "confirmed_retention" else "rejected"
    days = settings.delete_image_after_days if status == "confirmed" else settings.delete_rejected_after_days
    evidence = [value for value in (getattr(expense, f"{status}_at"), expense.image_replenished_at) if value is not None]
    return expense.status == status and days > 0 and bool(evidence) and max(evidence) <= now_utc() - timedelta(days=days)


def _audit(db: Session, expense: Expense, request: CleanupRequest, action: str, actor_account_id: int | None) -> None:
    db.add(LedgerAuditLog(
        ledger_id=expense.tenant_id, actor_account_id=actor_account_id, action=action,
        resource_type="expense", resource_public_id=expense.public_id,
        detail=json.dumps({"request_id": str(request.request_id), "reason": request.reason,
                           "outcomes": {kind: item.outcome for kind in ("image", "thumbnail")
                                        if (item := getattr(request, kind)) is not None}}),
    ))


def _file_result(item: CleanupFile, *, outcome: str = "pending", error_code: str | None = None) -> CleanupFile:
    return CleanupFile(reference=item.reference, outcome=outcome,
                       completed_at=now_utc() if outcome != "pending" else None, error_code=error_code)


def _settle_file(item: CleanupFile, tenant_id: str, *, delete_enabled: bool, cancel_remaining: bool) -> tuple[CleanupFile, int]:
    if item.outcome != "pending":
        return item, 0
    candidate = resolve_upload_path_for_tenant(item.reference, tenant_id)
    if candidate is None:
        if cancel_remaining:
            return _file_result(item, outcome="cancelled"), 0
        return _file_result(item, error_code="invalid_reference"), 0
    try:
        if not candidate.exists():
            # The durable request explains this reference; this run removed no bytes.
            return _file_result(item, outcome="deleted"), 0
        if cancel_remaining:
            return _file_result(item, outcome="cancelled"), 0
        if not candidate.is_file():
            return _file_result(item, error_code="invalid_reference"), 0
        if not delete_enabled:
            return item, 0
        candidate.unlink()
    except OSError:
        if cancel_remaining:
            return _file_result(item, outcome="cancelled"), 0
        return _file_result(item, error_code="unlink_failed"), 0
    return _file_result(item, outcome="deleted"), 1


def _mark_current_deleted(expense: Expense, kind: str, item: CleanupFile) -> bool:
    marker = f"{kind}_deleted_at"
    if (item.outcome != "deleted" or getattr(expense, f"{kind}_path") != item.reference
            or getattr(expense, marker) is not None):
        return False
    setattr(expense, marker, item.completed_at)
    return True


def settle_cleanup_request(
    db: Session, expense: Expense, *, expected_request_id: UUID, cancel_remaining: bool = False,
    actor_account_id: int | None = None, settings=None,
) -> CleanupSettlement:
    """Caller holds the Expense row lock and owns OCC + commit/rollback.

    Only a previously committed request may enter here. The expected ID prevents
    an old continuation from consuming a later request. This stages attachment
    metadata/audit, never a financial revision or its own row-version claim.
    """
    request = read_cleanup_request(expense)
    if request is None or request.request_id != expected_request_id:
        return CleanupSettlement(pending=request is not None)
    authorize_currency_metadata_write(db)
    delete_enabled = cleanup_policy_enabled(request, settings or get_settings())
    items, counts = {}, {}
    marker_changed = False
    for kind in ("image", "thumbnail"):
        item = getattr(request, kind)
        if item is None:
            items[kind], counts[kind] = None, 0
            continue
        updated, counts[kind] = _settle_file(item, expense.tenant_id, delete_enabled=delete_enabled,
                                            cancel_remaining=cancel_remaining)
        items[kind] = updated
        marker_changed |= _mark_current_deleted(expense, kind, updated)
    updated_request = CleanupRequest(request_id=request.request_id, reason=request.reason,
                                     requested_at=request.requested_at, **items)
    pending = any(item and item.outcome == "pending" for item in items.values())
    changed = updated_request != request or marker_changed or not pending
    if changed:
        expense.attachment_cleanup_request = updated_request.model_dump(mode="json") if pending else None
        expense.updated_at = now_utc()
        if not pending:
            _audit(db, expense, updated_request, "attachment_cleanup_cancelled" if cancel_remaining
                   else "attachment_cleanup_completed", actor_account_id)
    return CleanupSettlement(changed, counts["image"], counts["thumbnail"], pending)


def execute_attachment_cleanup(
    db: Session, expense: Expense, *, reason: str, settings_provider: Callable,
    actor_account_id: int | None = None,
) -> CleanupSettlement:
    """Automatic cleanup owns two short transactions around durable acceptance."""
    authorize_currency_metadata_write(db)
    db.refresh(expense, with_for_update=True)
    request = read_cleanup_request(expense)
    if request is None:
        settings = settings_provider()
        if not _retention_due(expense, reason, settings):
            return CleanupSettlement()
        request = _new_request(expense, reason)
        if request is None or not cleanup_policy_enabled(request, settings):
            return CleanupSettlement()
        expense.attachment_cleanup_request = request.model_dump(mode="json")
        expense.updated_at = now_utc()
        bump_row_version(expense)
        _audit(db, expense, request, "attachment_cleanup_requested", actor_account_id)
        db.commit()
        # No unlink follows a failed/uncertain acceptance commit. A new call may
        # recover the durable ID if COMMIT succeeded but its acknowledgement did not.
        authorize_currency_metadata_write(db)
        db.refresh(expense, with_for_update=True)
    result = settle_cleanup_request(db, expense, expected_request_id=request.request_id,
                                    actor_account_id=actor_account_id, settings=settings_provider())
    if result.changed:
        bump_row_version(expense)
        db.commit()
    return result
