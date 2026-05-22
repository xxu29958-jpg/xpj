"""Owner Console diagnostics page (single endpoint)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.routes.owner_console._shared import LocalOnly, _base, templates
from app.services import owner_console_service as svc

router = APIRouter(prefix="/owner", tags=["owner-console"])


@router.get("/diagnostics", response_class=HTMLResponse)
def owner_diagnostics(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    vm = svc.get_index_vm(db)
    cfg = get_settings()
    ctx = _base(request, db)
    ctx.update(vm.__dict__)
    ctx["ocr_provider"] = cfg.ocr_provider
    ctx["ocr_auto_run"] = cfg.ocr_auto_run
    ctx["enable_http_bootstrap"] = cfg.enable_http_bootstrap
    ctx["max_upload_size_mb"] = cfg.max_upload_size_mb
    return templates.TemplateResponse(request=request, name="diagnostics.html", context=ctx)
