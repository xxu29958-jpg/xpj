from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.database import get_db
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
    claim_idempotent_request,
    mark_idempotency_succeeded,
)
from app.services.merchant_alias_service import (
    create_merchant_alias,
    delete_merchant_alias,
    get_merchant_alias,
    list_merchant_aliases,
    undo_delete_merchant_alias,
    update_merchant_alias,
)
from app.services.merchant_catalog_service import (
    create_merchant_catalog,
    delete_merchant_catalog,
    list_merchant_catalog,
    merge_merchant_catalog,
    update_merchant_catalog,
)
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
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> MerchantCatalogResponse:
    return create_merchant_catalog(
        db,
        tenant_id=auth.tenant_id,
        display_name=payload.display_name,
        status=payload.status,
    )


@router.patch("/catalog/{public_id}", response_model=MerchantCatalogResponse)
def patch_merchant_catalog(
    public_id: str,
    payload: MerchantCatalogUpdateRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> MerchantCatalogResponse:
    return update_merchant_catalog(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        expected_row_version=payload.expected_row_version,
        display_name=payload.display_name,
        status=payload.status,
    )


@router.delete("/catalog/{public_id}", response_model=MerchantCatalogResponse)
def delete_merchant_catalog_route(
    public_id: str,
    payload: MerchantCatalogDeleteRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> MerchantCatalogResponse:
    return delete_merchant_catalog(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        expected_row_version=payload.expected_row_version,
    )


@router.post(
    "/catalog/{source_public_id}/merge",
    response_model=MerchantCatalogMergeResponse,
)
def merge_merchant_catalog_route(
    source_public_id: str,
    payload: MerchantCatalogMergeRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> MerchantCatalogMergeResponse:
    return merge_merchant_catalog(
        db,
        tenant_id=auth.tenant_id,
        source_public_id=source_public_id,
        expected_row_version=payload.expected_row_version,
        target_public_id=payload.target_public_id,
        target_row_version=payload.target_row_version,
        alias_policy=payload.alias_policy,
        rewrite_historical_expenses=payload.rewrite_historical_expenses,
    )


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
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> MerchantAliasResponse:
    return create_merchant_alias(
        db,
        tenant_id=auth.tenant_id,
        canonical_merchant=payload.canonical_merchant,
        alias=payload.alias,
        enabled=payload.enabled,
    )


@router.patch("/aliases/{public_id}", response_model=MerchantAliasResponse)
def patch_merchant_alias(
    public_id: str,
    payload: MerchantAliasUpdateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> MerchantAliasResponse:
    # ADR-0038 PR-2e: ``expected_row_version`` token gates the PATCH (409 on
    # stale snapshot). ADR-0042: claim the Idempotency-Key before that OCC claim.
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=auth.tenant_id,
        operation="update_merchant_alias",
        target_id=public_id,
        body=payload.model_dump(
            mode="json", exclude_unset=True, exclude={"expected_row_version"}
        ),
        expected_row_version=payload.expected_row_version,
        target_type="merchant_alias",
    )
    if claim is None:  # §4.6 HIT — re-serialise the current alias
        return get_merchant_alias(db, tenant_id=auth.tenant_id, public_id=public_id)

    item = get_merchant_alias(db, tenant_id=auth.tenant_id, public_id=public_id)
    field_updates = payload.model_dump(
        exclude={"expected_row_version"}, exclude_unset=True
    )
    result = update_merchant_alias(
        db,
        item,
        expected_row_version=payload.expected_row_version,
        commit=False,
        **field_updates,
    )
    mark_idempotency_succeeded(
        db, claim, resource_type="merchant_alias", resource_id=public_id
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
