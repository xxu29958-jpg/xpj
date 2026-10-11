from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.database import get_db
from app.errors import AppError
from app.schemas import (
    MerchantAliasCreateRequest,
    MerchantAliasDeleteRequest,
    MerchantAliasListResponse,
    MerchantAliasResponse,
    MerchantAliasUpdateRequest,
    MerchantCatalogCreateRequest,
    MerchantCatalogDeleteRequest,
    MerchantCatalogListResponse,
    MerchantCatalogMergeRequest,
    MerchantCatalogMergeResponse,
    MerchantCatalogResponse,
    MerchantCatalogUpdateRequest,
    StatusResponse,
)
from app.services.idempotency import (
    IdempotencyOutcome,
    IdempotencyOutcomeKind,
    claim_idempotency_key,
    claim_idempotent_request,
    fingerprint_request,
    mark_idempotency_succeeded,
)
from app.services.merchant_alias_service import (
    delete_merchant_alias,
    get_merchant_alias,
    list_merchant_aliases,
    undo_delete_merchant_alias,
    update_merchant_alias,
)
from app.services.merchant_catalog_command_service import submit_catalog_command
from app.services.merchant_catalog_service import (
    list_merchant_catalog,
)
from app.services.merchant_creation_service import submit_merchant_creation
from app.tenants import AuthContext

router = APIRouter(
    prefix="/api/merchants",
    tags=["merchants"],
)


@router.get("/catalog", response_model=MerchantCatalogListResponse)
def get_merchant_catalog(
    include_hidden: bool = Query(default=True),
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> MerchantCatalogListResponse:
    return MerchantCatalogListResponse(
        items=list_merchant_catalog(
            db,
            tenant_id=auth.tenant_id,
            include_hidden=include_hidden,
        )
    )


@router.post("/catalog", response_model=MerchantCatalogResponse, status_code=201)
def post_merchant_catalog(
    payload: MerchantCatalogCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> MerchantCatalogResponse:
    return submit_merchant_creation(db, tenant_id=auth.tenant_id, actor_account_id=auth.account_id,
        payload=payload, idempotency_key=idempotency_key)


@router.patch("/catalog/{public_id}", response_model=MerchantCatalogResponse)
def patch_merchant_catalog(
    public_id: str,
    payload: MerchantCatalogUpdateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> MerchantCatalogResponse:
    return submit_catalog_command(db, tenant_id=auth.tenant_id, actor_account_id=auth.account_id,
        public_id=public_id, payload=payload, idempotency_key=idempotency_key)


@router.delete("/catalog/{public_id}", response_model=MerchantCatalogResponse)
def delete_merchant_catalog_route(
    public_id: str,
    payload: MerchantCatalogDeleteRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> MerchantCatalogResponse:
    return submit_catalog_command(db, tenant_id=auth.tenant_id, actor_account_id=auth.account_id,
        public_id=public_id, payload=payload, idempotency_key=idempotency_key)


@router.post(
    "/catalog/{source_public_id}/merge",
    response_model=MerchantCatalogMergeResponse,
)
def merge_merchant_catalog_route(
    source_public_id: str,
    payload: MerchantCatalogMergeRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> MerchantCatalogMergeResponse:
    return submit_catalog_command(db, tenant_id=auth.tenant_id, actor_account_id=auth.account_id,
        public_id=source_public_id, payload=payload, idempotency_key=idempotency_key)


@router.get("/aliases", response_model=MerchantAliasListResponse)
def get_merchant_aliases(
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> MerchantAliasListResponse:
    return MerchantAliasListResponse(
        items=list_merchant_aliases(db, auth.tenant_id)
    )


@router.post("/aliases", response_model=MerchantAliasResponse, status_code=201)
def post_merchant_alias(
    payload: MerchantAliasCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> MerchantAliasResponse:
    return submit_merchant_creation(db, tenant_id=auth.tenant_id, actor_account_id=auth.account_id,
        payload=payload, idempotency_key=idempotency_key)


def _accepted_alias_update(claim: IdempotencyOutcome, public_id: str, expected_row_version: int) -> MerchantAliasResponse:
    try:
        receipt = MerchantAliasResponse.model_validate(claim.row.response_body)
        if (receipt.public_id != public_id or receipt.public_id != claim.row.resource_id
                or receipt.row_version != expected_row_version + 1):
            raise ValueError("Mismatched original alias receipt")
        return receipt
    except (ValidationError, ValueError) as exc:
        raise AppError("merchant_alias_original_requires_review",
            "原修改已被接受，但缺少可核对的原回执。请核对商家别名后继续。", status_code=409) from exc


@router.patch("/aliases/{public_id}", response_model=MerchantAliasResponse)
def patch_merchant_alias(
    public_id: str,
    payload: MerchantAliasUpdateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> MerchantAliasResponse:
    # Keep the original fingerprint and claim before both OCC and a current-row
    # read. Returning a peer's newer version would rebase the next outbox intent
    # over an unseen edit; a deleted current row cannot erase an accepted result.
    if not idempotency_key:
        raise AppError("idempotency_key_required", status_code=422)
    if len(idempotency_key) > 64:
        raise AppError("invalid_request", status_code=422)
    claim = claim_idempotency_key(db, tenant_id=auth.tenant_id, idempotency_key=idempotency_key,
        operation="update_merchant_alias", target_type="merchant_alias", target_id=public_id,
        request_fingerprint=fingerprint_request(operation="update_merchant_alias", target_id=public_id,
            body=payload.model_dump(mode="json", exclude_unset=True, exclude={"expected_row_version"}),
            expected_row_version=payload.expected_row_version))
    if claim.kind is IdempotencyOutcomeKind.HIT:
        return _accepted_alias_update(claim, public_id, payload.expected_row_version)
    if claim.kind is IdempotencyOutcomeKind.IN_PROGRESS:
        raise AppError("idempotency_key_in_progress", status_code=409)
    if claim.kind is IdempotencyOutcomeKind.FINGERPRINT_MISMATCH:
        raise AppError("idempotency_key_reused", status_code=422)

    item = get_merchant_alias(db, tenant_id=auth.tenant_id, public_id=public_id)
    field_updates = payload.model_dump(
        exclude={"expected_row_version"}, exclude_unset=True
    )
    result = MerchantAliasResponse.model_validate(update_merchant_alias(
        db,
        item,
        expected_row_version=payload.expected_row_version,
        commit=False,
        **field_updates,
    ))
    mark_idempotency_succeeded(
        db, claim.row, resource_type="merchant_alias", resource_id=public_id,
        response_body=result.model_dump(mode="json"),
    )
    db.commit()
    return result


@router.delete("/aliases/{public_id}", response_model=StatusResponse)
def delete_merchant_alias_route(
    public_id: str,
    payload: MerchantAliasDeleteRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> StatusResponse:
    # ADR-0038 PR-2e: DELETE carries ``expected_row_version`` (stale → 409).
    # ADR-0042: claim the key before the OCC claim; HIT = already deleted.
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=auth.tenant_id,
        operation="delete_merchant_alias",
        target_id=public_id,
        body=payload.model_dump(
            mode="json", exclude_unset=True, exclude={"expected_row_version"}
        ),
        expected_row_version=payload.expected_row_version,
        target_type="merchant_alias",
    )
    if claim is None:  # §4.6 HIT — already deleted
        return StatusResponse()

    item = get_merchant_alias(db, tenant_id=auth.tenant_id, public_id=public_id)
    delete_merchant_alias(
        db, item, expected_row_version=payload.expected_row_version, commit=False
    )
    mark_idempotency_succeeded(
        db, claim, resource_type="merchant_alias", resource_id=public_id
    )
    db.commit()
    return StatusResponse()


@router.post("/aliases/{public_id}/undo", response_model=MerchantAliasResponse)
def undo_merchant_alias_route(
    public_id: str,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> MerchantAliasResponse:
    # ADR-0038 undo: restore a soft-deleted alias within the retention window.
    # No ``expected_row_version`` token — this restores the row the caller just
    # soft-deleted (near-zero contention inside the undo window). 404 once
    # cleanup has purged it past retention.
    return undo_delete_merchant_alias(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        actor_account_id=auth.account_id,
    )
