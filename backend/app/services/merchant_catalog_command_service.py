"""The original catalog operation and its receipt commit with the existing facts."""
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.schemas import (
    MerchantCatalogDeleteRequest,
    MerchantCatalogMergeRequest,
    MerchantCatalogMergeResponse,
    MerchantCatalogResponse,
    MerchantCatalogUpdateRequest,
)
from app.services.idempotency import (
    IdempotencyOutcome,
    IdempotencyOutcomeKind,
    claim_idempotency_key,
    fingerprint_request,
    mark_idempotency_succeeded,
)
from app.services.merchant_catalog_service import (
    delete_merchant_catalog,
    merge_merchant_catalog,
    update_merchant_catalog,
)

CatalogCommand = MerchantCatalogUpdateRequest | MerchantCatalogDeleteRequest | MerchantCatalogMergeRequest
CatalogReceipt = MerchantCatalogResponse | MerchantCatalogMergeResponse


def submit_catalog_command(
    db: Session, *, tenant_id: str, actor_account_id: int | None, public_id: str,
    payload: CatalogCommand, idempotency_key: str | None,
) -> CatalogReceipt:
    if not idempotency_key:
        raise AppError("idempotency_key_required", status_code=422)
    if len(idempotency_key) > 64:
        raise AppError("invalid_request", status_code=422)
    verb = "update" if isinstance(payload, MerchantCatalogUpdateRequest) else (
        "delete" if isinstance(payload, MerchantCatalogDeleteRequest) else "merge")
    operation = f"{verb}_merchant_catalog"
    claim = claim_idempotency_key(db, tenant_id=tenant_id, idempotency_key=idempotency_key,
        operation=operation, target_type="merchant_catalog", target_id=public_id,
        request_fingerprint=fingerprint_request(operation=operation, target_id=public_id,
            expected_row_version=payload.expected_row_version,
            body={**payload.model_dump(mode="json"), "actor_account_id": actor_account_id}))
    if claim.kind is IdempotencyOutcomeKind.HIT:
        return _accepted_receipt(claim, public_id, payload)
    if claim.kind is IdempotencyOutcomeKind.FINGERPRINT_MISMATCH:
        raise AppError("idempotency_key_reused", status_code=422)
    if claim.kind is IdempotencyOutcomeKind.IN_PROGRESS:
        raise AppError("idempotency_key_in_progress", status_code=409)
    receipt = _apply_catalog_command(db, tenant_id, public_id, payload)
    mark_idempotency_succeeded(db, claim.row, resource_type="merchant_catalog", resource_id=public_id,
        response_body=receipt.model_dump(mode="json"))
    db.commit()
    return receipt


def _apply_catalog_command(db: Session, tenant_id: str, public_id: str, payload: CatalogCommand) -> CatalogReceipt:
    if isinstance(payload, MerchantCatalogMergeRequest):
        return MerchantCatalogMergeResponse.model_validate(merge_merchant_catalog(db,
            tenant_id=tenant_id, source_public_id=public_id, **payload.model_dump()))
    if isinstance(payload, MerchantCatalogDeleteRequest):
        item = delete_merchant_catalog(db, tenant_id=tenant_id, public_id=public_id,
            expected_row_version=payload.expected_row_version)
    else:
        item = update_merchant_catalog(db, tenant_id=tenant_id, public_id=public_id, **payload.model_dump())
    return MerchantCatalogResponse.model_validate(item)


def _require_original_snapshot(item: MerchantCatalogResponse, public_id: str, expected_row_version: int) -> None:
    if item.public_id != public_id or item.row_version != expected_row_version + 1:
        raise ValueError("Mismatched original catalog snapshot")


def _accepted_receipt(claim: IdempotencyOutcome, public_id: str, payload: CatalogCommand) -> CatalogReceipt:
    try:
        if claim.row.resource_id != public_id:
            raise ValueError("Mismatched original catalog command")
        if isinstance(payload, MerchantCatalogMergeRequest):
            receipt = MerchantCatalogMergeResponse.model_validate(claim.row.response_body)
            _require_original_snapshot(receipt.source, public_id, payload.expected_row_version)
            _require_original_snapshot(receipt.target, payload.target_public_id, payload.target_row_version)
            if (receipt.source.status != "merged" or receipt.source.merged_into_public_id != payload.target_public_id
                    or receipt.target.status != "active"
                    or (receipt.created_alias_public_id is not None) != (payload.alias_policy == "create_source_alias")):
                raise ValueError("Mismatched original merge result")
        else:
            receipt = MerchantCatalogResponse.model_validate(claim.row.response_body)
            _require_original_snapshot(receipt, public_id, payload.expected_row_version)
            if isinstance(payload, MerchantCatalogDeleteRequest) and receipt.deleted_at is None:
                raise ValueError("Missing original deletion result")
        return receipt
    except (ValidationError, ValueError) as exc:
        raise AppError("merchant_catalog_original_requires_review",
            "原商家操作已被接受，但缺少可核对的原回执。请核对商家资料后继续。", status_code=409) from exc
