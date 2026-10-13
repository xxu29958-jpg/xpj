"""Explicit category/tag creation in the existing library tables and receipt protocol.

This command creates an unused option. It never restores, renames, links, or
rewrites an expense; those operations retain their existing command owners.
"""
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import CategoryPreference, Tag
from app.schemas._reference_creation import ReferenceCreatedResponse, ReferenceKind
from app.services.category_preference_service import clean_category_name, default_category_keys
from app.services.currency_binding_service import authorize_currency_metadata_write
from app.services.idempotency import (
    IdempotencyOutcome,
    IdempotencyOutcomeKind,
    claim_idempotency_key,
    fingerprint_request,
    mark_idempotency_succeeded,
)
from app.services.resource_audit import record_resource_action
from app.tag_text import TAG_SEPARATOR_RE, clean_tag_name


def _reference_name(kind: ReferenceKind, name: str) -> str:
    if kind == "tag" and TAG_SEPARATOR_RE.search(name):
        raise AppError("invalid_request", "一次添加一个标签，名称不能含逗号、分号或换行。", status_code=422)
    cleaned = clean_category_name(name) if kind == "category" else clean_tag_name(name)
    if not cleaned or max(len(cleaned), len(cleaned.casefold())) > 64:
        raise AppError("invalid_request", "名称需为 1 至 64 个字符。", status_code=422)
    return cleaned


def _name_conflict(row: CategoryPreference | Tag) -> AppError:
    deleted = row.deleted_at is not None
    return AppError("reference_name_conflict",
        "同名对象已在回收站，请从回收站恢复。原输入仍保留。" if deleted else "已有同名对象，请使用现有对象或修改名称。",
        status_code=409, details={"public_id": row.public_id, "deleted": deleted})


def _accepted_receipt(claim: IdempotencyOutcome, kind: ReferenceKind) -> ReferenceCreatedResponse:
    try:
        receipt = ReferenceCreatedResponse.model_validate(claim.row.response_body)
        if receipt.kind != kind or receipt.public_id != claim.row.resource_id:
            raise ValueError("Mismatched reference receipt")
        return receipt
    except (ValidationError, ValueError) as exc:
        raise AppError("state_conflict", "原添加已被接受，请核对资料库中的对象。", status_code=409) from exc


def create_reference(
    db: Session, *, tenant_id: str, actor_account_id: int | None, kind: ReferenceKind,
    name: str, idempotency_key: str | None,
) -> ReferenceCreatedResponse:
    cleaned = _reference_name(kind, name)
    if not idempotency_key:
        raise AppError("idempotency_key_required", status_code=422)
    if len(idempotency_key) > 64:
        raise AppError("invalid_request", status_code=422)
    authorize_currency_metadata_write(db)
    operation = f"create_reference_{kind}"
    resource_type = "category_preference" if kind == "category" else "tag"
    claim = claim_idempotency_key(db, tenant_id=tenant_id, idempotency_key=idempotency_key,
        operation=operation, target_type=resource_type, request_fingerprint=fingerprint_request(
            operation=operation, target_id=None, expected_row_version=None,
            body={"name": cleaned, "actor_account_id": actor_account_id}))
    if claim.kind is IdempotencyOutcomeKind.HIT:
        return _accepted_receipt(claim, kind)
    if claim.kind is IdempotencyOutcomeKind.FINGERPRINT_MISMATCH:
        raise AppError("idempotency_key_reused", status_code=422)
    if claim.kind is IdempotencyOutcomeKind.IN_PROGRESS:
        raise AppError("idempotency_key_in_progress", status_code=409)
    if kind == "category" and cleaned.casefold() in default_category_keys():
        db.rollback()
        raise AppError("reference_name_conflict", "这是内置分类，已经可以使用。", status_code=409)
    model = CategoryPreference if kind == "category" else Tag
    lookup = select(model).where(model.tenant_id == tenant_id, model.key == cleaned.casefold())
    existing = db.scalar(lookup)
    if existing is not None:
        error = _name_conflict(existing)
        db.rollback()
        raise error
    row = model(tenant_id=tenant_id, name=cleaned, key=cleaned.casefold())
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(lookup)
        if existing is None:
            raise
        raise _name_conflict(existing) from None
    receipt = ReferenceCreatedResponse(kind=kind, public_id=row.public_id, name=row.name, row_version=row.row_version)
    record_resource_action(db, ledger_id=tenant_id, action="create", resource_type=resource_type,
        resource_public_id=row.public_id, actor_account_id=actor_account_id)
    mark_idempotency_succeeded(db, claim.row, resource_type=resource_type, resource_id=row.public_id,
        response_body=receipt.model_dump(mode="json"))
    db.commit()
    return receipt
