"""Tag management API — online creation and OCC-protected editing.

Creation retains an original Idempotency-Key receipt. Rename/delete/merge/undo
retain their online OCC protocol. Writes require the writer role.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header
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
from app.schemas._reference_creation import ReferenceCreatedResponse, ReferenceCreateRequest
from app.services.reference_creation_service import create_reference
from app.services.tag_management_service import (
    delete_tag,
    list_tags_with_usage,
    merge_tags,
    rename_tag,
)
from app.services.tag_undo_service import undo_tag_mutation
from app.tenants import AuthContext

router = APIRouter(prefix="/api/tags", tags=["tags"])


@router.post("", response_model=ReferenceCreatedResponse, status_code=201)
def create_tag_route(
    payload: ReferenceCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> ReferenceCreatedResponse:
    return create_reference(db, tenant_id=auth.tenant_id, actor_account_id=auth.account_id,
        kind="tag", name=payload.name, idempotency_key=idempotency_key)


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
        require_orphan=payload.require_orphan,
        actor_account_id=auth.account_id,
        actor_device_id=auth.device_id,
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
        require_orphan=payload.require_orphan,
        actor_account_id=auth.account_id,
        actor_device_id=auth.device_id,
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
        require_orphan=payload.require_orphan,
        actor_account_id=auth.account_id,
        actor_device_id=auth.device_id,
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
        actor_device_id=auth.device_id,
    )
