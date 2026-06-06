"""ADR-0043 tag management API — online-only rename / delete / merge / undo.

Online-only mutate surface (契约 7): every mutation carries
``expected_row_version`` (OCC) in its body and NONE declare an
``Idempotency-Key`` header (declaring it would make it required and route the
request through the idempotency replay path). Writes require the ``writer``
role; viewer → 403 via ``get_current_writer_context``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.database import get_db
from app.schemas import (
    TagDeleteRequest,
    TagDetailResponse,
    TagManagementListResponse,
    TagMergeRequest,
    TagMutationResponse,
    TagRenameRequest,
    TagUndoRequest,
    TagUndoResponse,
)
from app.services.tag_management_service import (
    delete_tag,
    list_tags_with_usage,
    merge_tags,
    rename_tag,
)
from app.services.tag_undo_service import undo_tag_mutation
from app.tenants import AuthContext

router = APIRouter(prefix="/api/tags", tags=["tags"])


@router.get("", response_model=TagManagementListResponse)
def get_tags(
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> TagManagementListResponse:
    return TagManagementListResponse(items=list_tags_with_usage(db, auth.tenant_id))


@router.post("/{public_id}/rename", response_model=TagDetailResponse)
def rename_tag_route(
    public_id: str,
    payload: TagRenameRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> TagDetailResponse:
    return rename_tag(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        expected_row_version=payload.expected_row_version,
        name=payload.name,
    )


@router.post("/{public_id}/delete", response_model=TagMutationResponse)
def delete_tag_route(
    public_id: str,
    payload: TagDeleteRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> TagMutationResponse:
    return delete_tag(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        expected_row_version=payload.expected_row_version,
        actor_account_id=auth.account_id,
    )


@router.post("/{public_id}/merge", response_model=TagMutationResponse)
def merge_tag_route(
    public_id: str,
    payload: TagMergeRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> TagMutationResponse:
    return merge_tags(
        db,
        tenant_id=auth.tenant_id,
        source_public_id=public_id,
        source_row_version=payload.expected_row_version,
        target_public_id=payload.target_public_id,
        target_row_version=payload.target_row_version,
        actor_account_id=auth.account_id,
    )


@router.post("/mutations/{mutation_public_id}/undo", response_model=TagUndoResponse)
def undo_tag_route(
    mutation_public_id: str,
    payload: TagUndoRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> TagUndoResponse:
    return undo_tag_mutation(
        db,
        tenant_id=auth.tenant_id,
        mutation_public_id=mutation_public_id,
        expected_row_version=payload.expected_row_version,
        actor_account_id=auth.account_id,
    )
