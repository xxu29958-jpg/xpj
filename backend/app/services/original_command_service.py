"""Same-bill attachment commands with actor, OCC and accepted-result ownership."""

import hashlib
import json
import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import ApiIdempotencyKey, Expense, LedgerAuditLog
from app.schemas._original_attachment import (
    OriginalCleanupRequest,
    OriginalCommandReceipt,
    OriginalOperation,
    OriginalReplenishmentRequest,
    OriginalVerificationRequest,
)
from app.services.attachment_cleanup_service import read_cleanup_request, settle_cleanup_request
from app.services.currency_binding_service import authorize_currency_metadata_write
from app.services.expense_query import get_expense
from app.services.file_service import delete_relative_upload, save_original_replenishment_bytes
from app.services.idempotency import (
    IdempotencyOutcomeKind,
    claim_idempotency_key,
    fingerprint_request,
    mark_idempotency_succeeded,
)
from app.services.optimistic_concurrency import claim_row_with_token
from app.services.original_read_service import read_original_snapshot, recorded_original_digest
from app.services.permission_service import require_write_expense
from app.services.session_credential_lock import lock_and_revalidate_mutation_actor
from app.services.time_service import now_utc
from app.tenants import AuthContext

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _OriginalClaim:
    record: ApiIdempotencyKey
    expense: Expense


def _claim_original_command(db: Session, *, expense_id: int, auth: AuthContext, operation: OriginalOperation,
                            expected_row_version: int, body: dict[str, object],
                            idempotency_key: str) -> _OriginalClaim | OriginalCommandReceipt:
    require_write_expense(auth)
    lock_and_revalidate_mutation_actor(db, auth, actor_account_id=auth.account_id, ledger_id=auth.ledger_id)
    if not idempotency_key:
        raise AppError("idempotency_key_required", status_code=422)
    if len(idempotency_key) > 64:
        raise AppError("invalid_request", status_code=422)
    fingerprint = fingerprint_request(operation=operation, target_id=str(expense_id),
        expected_row_version=expected_row_version,
        body={**body, "actor_account_id": auth.account_id, "actor_device_id": auth.device_id})
    claim = claim_idempotency_key(db, tenant_id=auth.tenant_id, idempotency_key=idempotency_key,
        operation=operation, request_fingerprint=fingerprint, target_type="expense", target_id=str(expense_id))
    if claim.kind is IdempotencyOutcomeKind.FINGERPRINT_MISMATCH:
        raise AppError("idempotency_key_reused", status_code=422)
    if claim.kind is IdempotencyOutcomeKind.IN_PROGRESS:
        raise AppError("idempotency_key_in_progress", status_code=409)
    if claim.kind is IdempotencyOutcomeKind.HIT:
        return OriginalCommandReceipt.model_validate(claim.row.response_body)
    authorize_currency_metadata_write(db)
    expense = get_expense(db, expense_id, auth.tenant_id)
    changed = claim_row_with_token(db, Expense, pk_id=expense_id, tenant_id=auth.tenant_id,
        expected_row_version=expected_row_version, set_values={"updated_at": now_utc()})
    if changed != 1:
        raise AppError("state_conflict", status_code=409)
    db.refresh(expense)
    return _OriginalClaim(claim.row, expense)


def _record_original_command(db: Session, claim: _OriginalClaim, *, auth: AuthContext,
                             operation: OriginalOperation, action: str, detail: dict[str, object],
                             cleanup_request_id: UUID | None = None,
                             cleanup_pending: bool | None = None) -> OriginalCommandReceipt:
    expense = claim.expense
    db.add(LedgerAuditLog(ledger_id=auth.ledger_id, actor_account_id=auth.account_id,
        resource_type="expense", resource_public_id=expense.public_id, action=action,
        detail=json.dumps(detail, ensure_ascii=False)))
    response = OriginalCommandReceipt(operation=operation, expense_id=expense.id, public_id=expense.public_id,
        row_version=expense.row_version, sha256=recorded_original_digest(expense.image_hash), accepted_at=now_utc(),
        cleanup_request_id=cleanup_request_id, cleanup_pending=cleanup_pending)
    mark_idempotency_succeeded(db, claim.record, resource_type="expense", resource_id=str(expense.id),
        response_body=response.model_dump(mode="json"))
    return response


def verify_original(db: Session, *, expense_id: int, auth: AuthContext,
                    payload: OriginalVerificationRequest, idempotency_key: str) -> OriginalCommandReceipt:
    """Adopt a reviewed legacy digest; verification never changes known identity."""
    try:
        claim = _claim_original_command(db, expense_id=expense_id, auth=auth, operation="verify_original",
            expected_row_version=payload.expected_row_version,
            body={"reviewed_sha256": payload.reviewed_sha256}, idempotency_key=idempotency_key)
        if isinstance(claim, OriginalCommandReceipt):
            return claim
        expense = claim.expense
        if recorded_original_digest(expense.image_hash) is not None:
            raise AppError("original_already_verified", status_code=409)
        if expense.image_deleted_at is not None:
            raise AppError("image_not_found", status_code=404)
        with read_original_snapshot(relative_path=expense.image_path, tenant_id=auth.tenant_id,
                                    expected_sha256=None) as snapshot:
            if snapshot.sha256 != payload.reviewed_sha256:
                raise AppError("original_review_conflict", status_code=409)
            expense.image_hash = snapshot.sha256
        receipt = _record_original_command(db, claim, auth=auth, operation="verify_original",
            action="original_verified", detail={"sha256": expense.image_hash, "basis": "current_review"})
        db.commit()
        return receipt
    except Exception:
        db.rollback()
        raise


def _retain_usable_thumbnail(expense: Expense) -> None:
    """Leave old cleanup references frozen while freeing the new source's cache."""
    try:
        request = read_cleanup_request(expense)
        covered = bool(request and request.thumbnail and request.thumbnail.reference == expense.thumbnail_path)
    except AppError as exc:
        if exc.error != "attachment_cleanup_invalid":
            raise
        # Do not interpret or execute an invalid request. Detach the derivative
        # conservatively so it can be rebuilt from the replenished original.
        covered = True
    if covered or expense.thumbnail_deleted_at is not None:
        expense.thumbnail_path = None
        expense.thumbnail_deleted_at = None


def _require_original_replenishment(expense: Expense) -> None:
    if expense.image_deleted_at is not None:
        return
    try:
        request = read_cleanup_request(expense)
    except AppError as exc:
        if exc.error != "attachment_cleanup_invalid":
            raise
        request = None
    if (request and request.image and request.image.outcome == "pending"
            and request.image.reference == expense.image_path):
        return
    try:
        with read_original_snapshot(relative_path=expense.image_path, tenant_id=expense.tenant_id,
                                    expected_sha256=expense.image_hash):
            pass
    except AppError as exc:
        if exc.error in {"image_not_found", "image_integrity_mismatch", "image_read_failed"}:
            return
        raise
    raise AppError("original_replenishment_not_needed", status_code=409)


def replenish_original(db: Session, *, expense_id: int, auth: AuthContext,
                       payload: OriginalReplenishmentRequest, data: bytes,
                       filename: str | None, content_type: str | None,
                       idempotency_key: str) -> OriginalCommandReceipt:
    """Publish the same admitted original under the existing bill, never overwrite."""
    saved = None
    commit_attempted = False
    try:
        claim = _claim_original_command(db, expense_id=expense_id, auth=auth, operation="replenish_original",
            expected_row_version=payload.expected_row_version, idempotency_key=idempotency_key,
            body={"expected_sha256": payload.expected_sha256, "upload_sha256": hashlib.sha256(data).hexdigest(),
                  "filename": filename, "content_type": content_type})
        if isinstance(claim, OriginalCommandReceipt):
            return claim
        expense = claim.expense
        expected = recorded_original_digest(expense.image_hash)
        if expected is None:
            raise AppError("original_identity_unverified", status_code=409)
        if expected != payload.expected_sha256:
            raise AppError("original_review_conflict", status_code=409)
        _require_original_replenishment(expense)
        saved = save_original_replenishment_bytes(data, tenant_id=auth.tenant_id, expected_sha256=expected,
            filename=filename, content_type=content_type)
        _retain_usable_thumbnail(expense)
        expense.image_path = saved.relative_path
        expense.image_perceptual_hash = saved.image_perceptual_hash
        expense.image_deleted_at = None
        expense.image_replenished_at = now_utc()
        receipt = _record_original_command(db, claim, auth=auth, operation="replenish_original",
            action="original_replenished", detail={"sha256": expected, "basis": "same_admitted_original"})
        # An uncertain COMMIT may already have published this path and receipt.
        # Keep its bytes; the unchanged client key resolves the accepted result.
        commit_attempted = True
        db.commit()
        return receipt
    except Exception:
        db.rollback()
        raise
    finally:
        if saved is not None and not commit_attempted:
            try:
                delete_relative_upload(saved.relative_path)
            except OSError as exc:
                logger.warning("Original staging compensation failed (%s)", type(exc).__name__)


def continue_original_cleanup(db: Session, *, expense_id: int, auth: AuthContext,
                              payload: OriginalCleanupRequest, cancel_remaining: bool,
                              idempotency_key: str) -> OriginalCommandReceipt:
    """Continue an already durable cleanup, or cancel its unexecuted files."""
    operation: OriginalOperation = "cancel_original_cleanup" if cancel_remaining else "retry_original_cleanup"
    try:
        claim = _claim_original_command(db, expense_id=expense_id, auth=auth, operation=operation,
            expected_row_version=payload.expected_row_version, body={"request_id": str(payload.request_id)},
            idempotency_key=idempotency_key)
        if isinstance(claim, OriginalCommandReceipt):
            return claim
        request = read_cleanup_request(claim.expense)
        if request is None or request.request_id != payload.request_id:
            raise AppError("attachment_cleanup_changed", status_code=409)
        result = settle_cleanup_request(db, claim.expense, expected_request_id=payload.request_id,
            cancel_remaining=cancel_remaining, actor_account_id=auth.account_id)
        receipt = _record_original_command(db, claim, auth=auth, operation=operation, action=operation,
            detail={"request_id": str(payload.request_id), "pending": result.pending},
            cleanup_request_id=payload.request_id, cleanup_pending=result.pending)
        db.commit()
        return receipt
    except Exception:
        db.rollback()
        raise
