"""/web/data-quality page (v0.4-alpha3 slice 2 / M4 / T20).

Pure read-only insights view. Reuses the same DataQualitySummary that
``GET /api/insights/data-quality`` exposes so /web and Android see the
exact same numbers.
"""

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
    templates,
)
from app.services.data_quality_service import data_quality_summary

router = APIRouter(prefix="/web", tags=["web"])


@router.get("/data-quality", response_class=HTMLResponse)
def web_data_quality(
    request: Request,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    summary = data_quality_summary(db, tenant_id=selected_id)
    ctx = _base_ctx(request, options=options, selected_ledger_id=selected_id)
    ctx["summary"] = summary
    return templates.TemplateResponse(
        request=request, name="data_quality.html", context=ctx
    )
