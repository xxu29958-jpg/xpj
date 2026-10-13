"""Saved financial queries for the authenticated app's current ledger."""

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.database import get_db
from app.schemas._saved_view import (
    SavedViewDefinitionRequest,
    SavedViewDeleteRequest,
    SavedViewListResponse,
    SavedViewResultsResponse,
    SavedViewUpdateRequest,
)
from app.services import saved_view_service as views
from app.services.saved_view_results import read_saved_view_results
from app.tenants import AuthContext

router = APIRouter(prefix="/api/saved-views", tags=["saved-views"])


@router.get("", response_model=SavedViewListResponse)
def list_saved_views(auth: AuthContext = Depends(get_current_app_context),
                     db: Session = Depends(get_db)) -> SavedViewListResponse:
    return SavedViewListResponse(items=views.list_views(db, tenant_id=auth.tenant_id, actor_account_id=auth.account_id))


@router.get("/{public_id}", response_model=views.SavedViewDetail)
def read_saved_view(public_id: str, auth: AuthContext = Depends(get_current_app_context),
                    db: Session = Depends(get_db)) -> views.SavedViewDetail:
    return views.read_view(db, tenant_id=auth.tenant_id, actor_account_id=auth.account_id, public_id=public_id)


@router.get("/{public_id}/results", response_model=SavedViewResultsResponse)
def saved_view_results(public_id: str, page: int = Query(default=1, ge=1),
                       page_size: int = Query(default=50, ge=1, le=200),
                       auth: AuthContext = Depends(get_current_app_context),
                       db: Session = Depends(get_db)) -> SavedViewResultsResponse:
    return read_saved_view_results(db, tenant_id=auth.tenant_id, actor_account_id=auth.account_id,
        public_id=public_id, page=page, page_size=page_size)


@router.post("", response_model=views.SavedViewDetail, status_code=201)
def create_saved_view(payload: SavedViewDefinitionRequest,
                      idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                      auth: AuthContext = Depends(get_current_writer_context),
                      db: Session = Depends(get_db)) -> views.SavedViewDetail:
    return views.create_view(db, tenant_id=auth.tenant_id, actor_account_id=auth.account_id,
        idempotency_key=idempotency_key, **payload.model_dump())


@router.patch("/{public_id}", response_model=views.SavedViewDetail)
def update_saved_view(public_id: str, payload: SavedViewUpdateRequest,
                      idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                      auth: AuthContext = Depends(get_current_writer_context),
                      db: Session = Depends(get_db)) -> views.SavedViewDetail:
    return views.update_view(db, tenant_id=auth.tenant_id, actor_account_id=auth.account_id,
        public_id=public_id, idempotency_key=idempotency_key, **payload.model_dump())


@router.delete("/{public_id}", response_model=views.SavedViewDeletionReceipt)
def delete_saved_view(public_id: str, payload: SavedViewDeleteRequest,
                      idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                      auth: AuthContext = Depends(get_current_writer_context),
                      db: Session = Depends(get_db)) -> views.SavedViewDeletionReceipt:
    return views.delete_view(db, tenant_id=auth.tenant_id, actor_account_id=auth.account_id,
        public_id=public_id, idempotency_key=idempotency_key, **payload.model_dump())
