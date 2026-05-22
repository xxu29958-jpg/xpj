"""/web/search SSR page."""

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
from app.services.web_search_service import search_web

router = APIRouter(prefix="/web", tags=["web"])


@router.get("/search", response_class=HTMLResponse)
def web_search(
    request: Request,
    q: str = "",
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options)
    query = (q or "").strip()
    ctx = _base_ctx(
        request,
        options=options,
        selected_ledger_id=selected_id,
        page_title="搜索",
        sidebar_counts=_sidebar_counts(db, selected_id),
    )
    groups = search_web(db, tenant_id=selected_id, query=query)
    ctx["search_query"] = query
    ctx["search_groups"] = groups
    ctx["search_total"] = sum(len(group.results) for group in groups)
    return templates.TemplateResponse(request=request, name="search.html", context=ctx)
