"""Merchant creation and its first receipt share the existing fact transaction.

Replaying an accepted creation never reads or recreates its current object.
The catalog and alias services remain the owners of names and business facts.
"""
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.schemas import (
    MerchantAliasCreateRequest,
    MerchantAliasResponse,
    MerchantCatalogCreateRequest,
    MerchantCatalogResponse,
)
from app.services.idempotency import (
    IdempotencyOutcomeKind,
    claim_idempotency_key,
    fingerprint_request,
    mark_idempotency_succeeded,
)
from app.services.merchant_alias_service import create_merchant_alias
from app.services.merchant_catalog_service import create_merchant_catalog


def submit_merchant_creation(
    db: Session, *, tenant_id: str, actor_account_id: int | None,
    payload: MerchantCatalogCreateRequest | MerchantAliasCreateRequest,
    idempotency_key: str | None,
) -> MerchantCatalogResponse | MerchantAliasResponse:
    if not idempotency_key:
        raise AppError("idempotency_key_required", status_code=422)
    if len(idempotency_key) > 64:
        raise AppError("invalid_request", status_code=422)
    catalog = isinstance(payload, MerchantCatalogCreateRequest)
    resource_type = "merchant_catalog" if catalog else "merchant_alias"
    operation = f"create_{resource_type}"
    response_type = MerchantCatalogResponse if catalog else MerchantAliasResponse
    claim = claim_idempotency_key(db, tenant_id=tenant_id, idempotency_key=idempotency_key,
        operation=operation, target_type=resource_type, request_fingerprint=fingerprint_request(
            operation=operation, target_id=None, expected_row_version=None,
            body={**payload.model_dump(mode="json"), "actor_account_id": actor_account_id}))
    if claim.kind is IdempotencyOutcomeKind.HIT:
        try:
            receipt = response_type.model_validate(claim.row.response_body)
            if receipt.public_id != claim.row.resource_id or receipt.row_version != 1:
                raise ValueError("Mismatched original merchant creation receipt")
            return receipt
        except (ValidationError, ValueError) as exc:
            raise AppError("merchant_creation_original_requires_review",
                "原添加已被接受，但缺少可核对的原回执。请核对商家资料后继续。", status_code=409) from exc
    if claim.kind is IdempotencyOutcomeKind.FINGERPRINT_MISMATCH:
        raise AppError("idempotency_key_reused", status_code=422)
    if claim.kind is IdempotencyOutcomeKind.IN_PROGRESS:
        raise AppError("idempotency_key_in_progress", status_code=409)
    if isinstance(payload, MerchantCatalogCreateRequest):
        item = create_merchant_catalog(db, tenant_id=tenant_id, display_name=payload.display_name,
            status=payload.status)
    else:
        item = create_merchant_alias(db, tenant_id=tenant_id, canonical_merchant=payload.canonical_merchant,
            alias=payload.alias, enabled=payload.enabled)
    receipt = response_type.model_validate(item)
    mark_idempotency_succeeded(db, claim.row, resource_type=resource_type, resource_id=receipt.public_id,
        response_body=receipt.model_dump(mode="json"))
    db.commit()
    return receipt
