from __future__ import annotations

from fastapi import APIRouter, Depends, Header
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
