"""ADR-0051 current-ledger recycle-bin API."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.database import get_db
from app.schemas import (
    RecycleBinItemResponse,
    RecycleBinListResponse,
    RecycleBinRestoreRequest,
    RecycleBinRestoreResponse,
)
from app.services.recycle_bin_service import (
    RecycleBinItem,
    list_recycle_bin_items,
    restore_recycle_bin_item,
)
from app.tenants import AuthContext

router = APIRouter(prefix="/api/recycle-bin", tags=["recycle-bin"])


def _to_response(item: RecycleBinItem) -> RecycleBinItemResponse:
    return RecycleBinItemResponse(
        kind=item.kind,
        kind_label=item.kind_label,
        resource_id=item.resource_id,
        title=item.title,
        detail=item.detail,
        removed_at=item.removed_at,
        retention_label=item.retention_label,
        expected_row_version=item.expected_row_version,
    )


@router.get("", response_model=RecycleBinListResponse)
def list_recycle_bin(
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> RecycleBinListResponse:
    listing = list_recycle_bin_items(db, tenant_id=auth.tenant_id)
    return RecycleBinListResponse(
        items=[_to_response(item) for item in listing.items],
        short_window_count=listing.short_window_count,
    )


@router.post("/restore", response_model=RecycleBinRestoreResponse)
def restore_recycle_bin(
    payload: RecycleBinRestoreRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> RecycleBinRestoreResponse:
    message = restore_recycle_bin_item(
        db,
        tenant_id=auth.tenant_id,
        kind=payload.kind,
        resource_id=payload.resource_id,
        expected_row_version=payload.expected_row_version,
        actor_account_id=auth.account_id,
    )
    return RecycleBinRestoreResponse(message=message)
