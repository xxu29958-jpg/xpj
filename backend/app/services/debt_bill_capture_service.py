"""One private source lifecycle; only the original Debt command may adopt it."""

import hashlib
from pathlib import Path

from sqlalchemy import and_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.errors import AppError
from app.models import ApiIdempotencyKey, DebtBillCapture
from app.schemas._debts import DebtBillSourceReference
from app.schemas.debt_bill_capture import DebtBillCaptureReceipt, DebtBillCaptureResponse
from app.schemas.image_source import ImageSourceContext
from app.services import permission_service
from app.services.attachment_publication_lock import retain_publication
from app.services.file_service import delete_relative_upload, save_upload_bytes
from app.services.idempotency import claim_idempotent_request, fingerprint_request, mark_idempotency_succeeded
from app.services.optimistic_concurrency import bump_row_version
from app.services.original_read_service import OriginalSnapshot, read_original_snapshot
from app.services.session_credential_lock import lock_and_revalidate_mutation_actor
from app.services.time_service import now_utc
from app.tenants import AuthContext

CAPTURE_RESOURCE = "debt_bill_capture"


def capture_scope(tenant_id: str, actor_account_id: int) -> ColumnElement[bool]:
    return and_(DebtBillCapture.tenant_id == tenant_id, DebtBillCapture.created_by_account_id == actor_account_id)


def authorize_capture_write(db: Session, auth: AuthContext) -> None:
    current = lock_and_revalidate_mutation_actor(db, auth, actor_account_id=auth.account_id, ledger_id=auth.ledger_id)
    if current is None:
        raise AppError("invalid_token", status_code=401)
    permission_service.require_write_expense(current)


def get_capture(db: Session, *, tenant_id: str, actor_account_id: int,
                public_id: str | None = None, capture_key: str | None = None,
                lock: bool = False) -> DebtBillCapture:
    query = select(DebtBillCapture).where(capture_scope(tenant_id, actor_account_id))
    query = query.where(DebtBillCapture.public_id == public_id) if public_id is not None else \
        query.where(DebtBillCapture.capture_key == capture_key)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    source = db.scalar(query)
    if source is None:
        raise AppError("debt_bill_capture_not_found", status_code=404)
    return source


def read_capture_original(source: DebtBillCapture) -> OriginalSnapshot:
    if source.image_deleted_at is not None:
        raise AppError("original_cleaned", status_code=410)
    return read_original_snapshot(relative_path=source.image_path, tenant_id=source.tenant_id,
                                  expected_sha256=source.image_hash)


def capture_response(source: DebtBillCapture) -> DebtBillCaptureResponse:
    state = "cleaned"
    if source.image_deleted_at is None:
        try:
            with read_capture_original(source):
                state = "verified"
        except AppError as error:
            state = {"image_not_found": "missing", "image_integrity_mismatch": "corrupt"}.get(error.error, "unreadable")
    return DebtBillCaptureResponse(
        public_id=source.public_id, creation_key=source.creation_key, capture_key=source.capture_key,
        row_version=source.row_version, input_sha256=source.input_sha256, image_hash=source.image_hash,
        status=source.status, file_name=source.file_name, media_type=source.media_type,
        image_size_bytes=source.image_size_bytes, image_evidence=source.image_evidence,
        original_state=state, adopted_debt_public_id=source.adopted_debt_public_id,
        parse_outcome=source.parse_outcome, created_at=source.created_at,
        confirmed_at=source.confirmed_at, rejected_at=source.rejected_at,
    )


def list_captures(db: Session, *, tenant_id: str, actor_account_id: int,
                  creation_key: str | None = None, debt_public_id: str | None = None) -> list[DebtBillCaptureResponse]:
    query = select(DebtBillCapture).where(capture_scope(tenant_id, actor_account_id))
    if creation_key is not None:
        query = query.where(DebtBillCapture.creation_key == creation_key)
    if debt_public_id is not None:
        query = query.where(DebtBillCapture.adopted_debt_public_id == debt_public_id)
    return [capture_response(row) for row in db.scalars(query.order_by(DebtBillCapture.id.desc()).limit(100))]


def accepted_capture_command(db: Session, *, tenant_id: str, key: str, fingerprint: str) -> dict | None:
    """Read the frozen result; the existing idempotency owner still arbitrates publication."""
    row = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.tenant_id == tenant_id,
        ApiIdempotencyKey.idempotency_key == key, ApiIdempotencyKey.status == "succeeded"))
    if row is None:
        return None
    if row.request_fingerprint != fingerprint:
        raise AppError("idempotency_key_reused", status_code=422)
    return row.response_body


def _stage_new_capture(db: Session, source: DebtBillCapture) -> None:
    """Freeze the creation receipt before later lifecycle changes can advance the row."""
    db.add(source)
    db.flush()
    source.accepted_receipt = DebtBillCaptureReceipt(public_id=source.public_id,
        creation_key=source.creation_key, capture_key=source.capture_key, row_version=source.row_version,
        input_sha256=source.input_sha256, image_hash=source.image_hash).model_dump(mode="json")


def capture_bill(db: Session, *, auth: AuthContext, creation_key: str, capture_key: str,
                 data: bytes, file_name: str, media_type: str | None,
                 source_context: ImageSourceContext | None) -> DebtBillCaptureReceipt:
    operation = "capture_debt_bill"
    digest = hashlib.sha256(data).hexdigest()
    body = {"creation_key": creation_key, "actor_account_id": auth.account_id,
            "input_sha256": digest, "file_name": file_name, "media_type": media_type,
            "source_context": source_context.model_dump(mode="json") if source_context else None}
    fingerprint = fingerprint_request(operation=operation, target_id=capture_key, body=body, expected_row_version=None)
    saved, commit_attempted = None, False
    try:
        authorize_capture_write(db, auth)
        claim = claim_idempotent_request(db, idempotency_key=capture_key, tenant_id=auth.ledger_id,
            operation=operation, target_id=capture_key, body=body, expected_row_version=None, target_type=CAPTURE_RESOURCE)
        if claim is None:
            return DebtBillCaptureReceipt.model_validate(accepted_capture_command(
                db, tenant_id=auth.ledger_id, key=capture_key, fingerprint=fingerprint))
        source = db.scalar(select(DebtBillCapture).where(DebtBillCapture.tenant_id == auth.ledger_id,
            DebtBillCapture.capture_key == capture_key).with_for_update())
        if source is None:
            saved = save_upload_bytes(data, tenant_id=auth.ledger_id, filename=file_name, content_type=media_type,
                source_context=source_context, before_publish=lambda reference: retain_publication(db, reference))
            source = DebtBillCapture(tenant_id=auth.ledger_id, created_by_account_id=auth.account_id,
                creation_key=creation_key, capture_key=capture_key, request_fingerprint=fingerprint,
                accepted_receipt={}, file_name=Path(file_name).name[:255], media_type=saved.media_type,
                input_sha256=digest, image_path=saved.relative_path, image_hash=saved.image_hash,
                image_size_bytes=saved.size_bytes, image_evidence=saved.image_evidence)
            _stage_new_capture(db, source)
        elif source.request_fingerprint != fingerprint or source.created_by_account_id != auth.account_id:
            raise AppError("idempotency_key_reused", status_code=422)
        result = DebtBillCaptureReceipt.model_validate(source.accepted_receipt)
        mark_idempotency_succeeded(db, claim, resource_type=CAPTURE_RESOURCE,
            resource_id=source.public_id, response_body=result.model_dump(mode="json"))
        commit_attempted = True
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        # Only an uncommitted publication may be removed; uncertain COMMIT keeps the original.
        if saved is not None and not commit_attempted:
            delete_relative_upload(saved.relative_path)


def require_pending_capture(source: DebtBillCapture, expected_row_version: int) -> None:
    if source.status != "pending" or source.row_version != expected_row_version:
        raise AppError("state_conflict", status_code=409)


def lock_capture_for_adoption(db: Session, *, tenant_id: str, actor_account_id: int,
                              creation_key: str, reference: DebtBillSourceReference) -> DebtBillCapture:
    source = get_capture(db, tenant_id=tenant_id, actor_account_id=actor_account_id,
                         public_id=reference.public_id, lock=True)
    require_pending_capture(source, reference.expected_row_version)
    if source.creation_key != creation_key:
        raise AppError("debt_bill_task_mismatch", status_code=422)
    with read_capture_original(source):
        pass
    return source


def stage_capture_adoption(db: Session, source: DebtBillCapture, debt_public_id: str) -> None:
    source.adopted_debt_public_id = debt_public_id
    source.status = "confirmed"
    source.confirmed_at = source.updated_at = now_utc()
    bump_row_version(source)
    db.flush()


def discard_capture(db: Session, *, auth: AuthContext, public_id: str,
                     expected_row_version: int, key: str) -> DebtBillCaptureResponse:
    operation, body = "discard_debt_bill", {"actor_account_id": auth.account_id}
    fingerprint = fingerprint_request(operation=operation, target_id=public_id,
        body=body, expected_row_version=expected_row_version)
    authorize_capture_write(db, auth)
    claim = claim_idempotent_request(db, idempotency_key=key, tenant_id=auth.ledger_id, operation=operation,
        target_id=public_id, body=body, expected_row_version=expected_row_version, target_type=CAPTURE_RESOURCE)
    if claim is None:
        return DebtBillCaptureResponse.model_validate(accepted_capture_command(
            db, tenant_id=auth.ledger_id, key=key, fingerprint=fingerprint))
    source = get_capture(db, tenant_id=auth.ledger_id, actor_account_id=auth.account_id, public_id=public_id, lock=True)
    require_pending_capture(source, expected_row_version)
    source.status, source.rejected_at, source.updated_at = "rejected", now_utc(), now_utc()
    bump_row_version(source)
    db.flush()
    result = capture_response(source)
    mark_idempotency_succeeded(db, claim, resource_type=CAPTURE_RESOURCE,
        resource_id=source.public_id, response_body=result.model_dump(mode="json"))
    db.commit()
    return result
