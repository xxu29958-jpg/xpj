"""Same-bill attachment commands with actor, OCC and accepted-result ownership."""

import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import ApiIdempotencyKey, Expense, LedgerAuditLog
from app.schemas._original_attachment import OriginalCommandReceipt, OriginalVerificationRequest
from app.services.currency_binding_service import authorize_currency_metadata_write
from app.services.expense_query import get_expense
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


@dataclass(frozen=True)
class _OriginalClaim:
    record: ApiIdempotencyKey
    expense: Expense


def _claim_original_command(db: Session, *, expense_id: int, auth: AuthContext, operation: str,
                            expected_row_version: int, body: dict[str, object],
                            idempotency_key: str) -> _OriginalClaim | OriginalCommandReceipt:
    require_write_expense(auth)
    lock_and_revalidate_mutation_actor(db, auth, actor_account_id=auth.account_id, ledger_id=auth.ledger_id)
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


def _complete_original_command(db: Session, claim: _OriginalClaim, *, auth: AuthContext,
                               operation: str, action: str, detail: dict[str, object]) -> OriginalCommandReceipt:
    expense = claim.expense
    db.add(LedgerAuditLog(ledger_id=auth.ledger_id, actor_account_id=auth.account_id,
        resource_type="expense", resource_public_id=expense.public_id, action=action,
        detail=json.dumps(detail, ensure_ascii=False)))
    response = OriginalCommandReceipt(operation=operation, expense_id=expense.id, public_id=expense.public_id,
        row_version=expense.row_version, sha256=recorded_original_digest(expense.image_hash), accepted_at=now_utc())
    mark_idempotency_succeeded(db, claim.record, resource_type="expense", resource_id=str(expense.id),
        response_body=response.model_dump(mode="json"))
    db.commit()
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
        return _complete_original_command(db, claim, auth=auth, operation="verify_original",
            action="original_verified", detail={"sha256": expense.image_hash, "basis": "current_review"})
    except Exception:
        db.rollback()
        raise
