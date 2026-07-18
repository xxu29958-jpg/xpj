"""Transactions library hub for category, merchant, tag, and rule assets."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _list_ledger_options,
    _resolve_selected_ledger_id,
    _sidebar_counts,
    templates,
)

router = APIRouter(prefix="/web", tags=["web"])


@router.get("/library", response_class=HTMLResponse)
def web_library(
    request: Request,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    ctx = _base_ctx(
        request,
        options=options,
        selected_ledger_id=selected_id,
        page_title="资料库",
        sidebar_counts=_sidebar_counts(db, selected_id),
    )
    return templates.TemplateResponse(
        request=request,
        name="library.html",
        context=ctx,
    )
