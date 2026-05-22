"""/web protected expense media routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.web_common import LocalOnly, _resolve_selected_ledger_id
from app.services.expense_service import ensure_image_file, ensure_thumbnail_file

router = APIRouter(prefix="/web", tags=["web"])


@router.get("/expenses/{expense_id}/image", include_in_schema=False)
def web_image(
    request: Request,
    expense_id: int,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> FileResponse:
    selected_id = _resolve_selected_ledger_id(db, ledger_id, request=request)
    path, media_type = ensure_image_file(db, expense_id, selected_id)
    return FileResponse(path=path, media_type=media_type)


@router.get("/expenses/{expense_id}/thumbnail", include_in_schema=False)
def web_thumbnail(
    request: Request,
    expense_id: int,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> FileResponse:
    selected_id = _resolve_selected_ledger_id(db, ledger_id, request=request)
    path, media_type = ensure_thumbnail_file(db, expense_id, selected_id)
    return FileResponse(path=path, media_type=media_type)
