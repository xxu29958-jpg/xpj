from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.database import get_db
from app.schemas import (
    MerchantAliasCreateRequest,
    MerchantAliasDeleteRequest,
    MerchantAliasListResponse,
    MerchantAliasResponse,
    MerchantAliasUpdateRequest,
    StatusResponse,
)
from app.services.merchant_alias_service import (
    create_merchant_alias,
    delete_merchant_alias,
    get_merchant_alias,
    list_merchant_aliases,
    update_merchant_alias,
)
from app.tenants import AuthContext

router = APIRouter(
    prefix="/api/merchants",
    tags=["merchants"],
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
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> MerchantAliasResponse:
    # ADR-0038 PR-2e: ``expected_updated_at`` token gates the PATCH;
    # ``state_conflict`` 409 on stale snapshot (peer edited the alias
    # between the client's read and this PATCH).
    item = get_merchant_alias(db, tenant_id=auth.tenant_id, public_id=public_id)
    field_updates = payload.model_dump(
        exclude={"expected_updated_at"}, exclude_unset=True
    )
    return update_merchant_alias(
        db,
        item,
        expected_updated_at=payload.expected_updated_at,
        **field_updates,
    )


@router.delete("/aliases/{public_id}", response_model=StatusResponse)
def delete_merchant_alias_route(
    public_id: str,
    payload: MerchantAliasDeleteRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> StatusResponse:
    # ADR-0038 PR-2e: DELETE carries a body with ``expected_updated_at``
    # (same shape as category_rule DELETE). Stale clicks against an
    # alias edited by another window between list-render and delete-
    # click surface as ``state_conflict`` 409 instead of silently
    # destroying the concurrent edit.
    item = get_merchant_alias(db, tenant_id=auth.tenant_id, public_id=public_id)
    delete_merchant_alias(db, item, expected_updated_at=payload.expected_updated_at)
    return StatusResponse()
