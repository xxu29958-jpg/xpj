"""A selected category batch and its first receipt share the existing transaction and key store."""
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import ApiIdempotencyKey
from app.services.idempotency import (
    IdempotencyOutcomeKind,
    claim_idempotency_key,
    fingerprint_request,
    mark_idempotency_succeeded,
)
from app.services.pending_review_bulk_service import BulkResult, apply_review_bulk

_OPERATION = "set_pending_categories"


class PendingCategoryReceipt(BaseModel):
    command_key: str
    category: str
    filter: str
    selected_versions: dict[int, int]
    result: BulkResult


def _original_receipt(row: ApiIdempotencyKey) -> PendingCategoryReceipt:
    try:
        receipt = PendingCategoryReceipt.model_validate(row.response_body)
        if (row.operation != _OPERATION or row.target_id != "pending"
                or row.resource_type != "pending_category_batch" or row.resource_id != row.idempotency_key
                or receipt.command_key != row.idempotency_key
                or not set(receipt.result.success_ids) <= set(receipt.selected_versions)
                or len(receipt.result.success_ids) + sum(receipt.result.skipped_reasons.values()) != len(receipt.selected_versions)):
            raise ValueError("Original category batch does not match its receipt")
        return receipt
    except (ValidationError, ValueError) as exc:
        raise AppError("category_batch_original_requires_review",
            "原分类操作已被接受，但原回执无法核对。请查看账单当前状态，勿重复提交。", status_code=409) from exc


def read_pending_category_receipt(db: Session, *, tenant_id: str, command_key: str) -> PendingCategoryReceipt | None:
    row = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.tenant_id == tenant_id,
        ApiIdempotencyKey.idempotency_key == command_key, ApiIdempotencyKey.status == "succeeded"))
    return _original_receipt(row) if row is not None else None


def submit_pending_category_batch(db: Session, *, tenant_id: str, selected_versions: dict[int, int],
    category: str, filter: str, command_key: str) -> PendingCategoryReceipt:
    if len(command_key) > 64 or not selected_versions:
        raise AppError("invalid_request", "请勾选要修改的账单。", status_code=422)
    if not command_key:
        raise AppError("idempotency_key_required", status_code=422)
    try:
        claim = claim_idempotency_key(db, tenant_id=tenant_id, idempotency_key=command_key,
            operation=_OPERATION, target_type="pending_category_batch", target_id="pending",
            request_fingerprint=fingerprint_request(operation=_OPERATION, target_id="pending",
                body={"selected_versions": selected_versions, "category": category, "filter": filter}, expected_row_version=None))
        if claim.kind is IdempotencyOutcomeKind.HIT:
            return _original_receipt(claim.row)
        if claim.kind is IdempotencyOutcomeKind.IN_PROGRESS:
            raise AppError("idempotency_key_in_progress", status_code=409)
        if claim.kind is IdempotencyOutcomeKind.FINGERPRINT_MISMATCH:
            raise AppError("idempotency_key_reused", status_code=422)
        result = apply_review_bulk(db, tenant_id=tenant_id, action="set_category", expense_ids=list(selected_versions),
            expected_row_version_by_id=selected_versions, category=category, category_commit=False)
        receipt = PendingCategoryReceipt(command_key=command_key, category=category.strip(), filter=filter,
            selected_versions=selected_versions, result=result)
        mark_idempotency_succeeded(db, claim.row, resource_type="pending_category_batch", resource_id=command_key,
            response_body=receipt.model_dump(mode="json"))
        db.commit()
        return receipt
    except (AppError, SQLAlchemyError):
        db.rollback()
        raise
