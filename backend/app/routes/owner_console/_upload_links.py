"""Owner Console upload-link list + per-link actions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.routes.owner_console._shared import LocalOnly, _base, templates
from app.services import owner_console_service as svc


router = APIRouter(prefix="/owner", tags=["owner-console"])


@router.get("/upload-links", response_class=HTMLResponse)
def owner_upload_links_get(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    links = svc.get_upload_links(db)
    ctx = _base(request, db)
    ctx["links"] = links
    ctx["new_secret"] = None
    ctx["new_secret_full_url"] = None
    ctx["public_base_url_configured"] = bool(get_settings().public_base_url)
    return templates.TemplateResponse(request=request, name="upload_links.html", context=ctx)


@router.post("/upload-links", response_class=HTMLResponse)
def owner_upload_links_create(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    ledger_id = svc.get_default_ledger_id(db)
    account_id = svc.get_owner_account_id(db)
    if ledger_id is None or account_id is None:
        ctx = _base(request, db)
        ctx["links"] = []
        ctx["new_secret"] = None
        ctx["new_secret_full_url"] = None
        ctx["public_base_url_configured"] = bool(get_settings().public_base_url)
        ctx["error"] = "服务未初始化，请先运行 bootstrap_dev_owner.ps1。"
        return templates.TemplateResponse(request=request, name="upload_links.html", context=ctx)
    cfg = get_settings()
    tz = (cfg.ocr_default_timezone or "Asia/Shanghai").strip() or "Asia/Shanghai"
    _summary, secret = svc.do_create_upload_link(
        db, ledger_id=ledger_id, admin_account_id=account_id, default_timezone=tz
    )
    links = svc.get_upload_links(db)
    ctx = _base(request, db)
    ctx["links"] = links
    ctx["new_secret"] = secret
    ctx["new_secret_full_url"] = svc.compose_public_upload_url(secret)
    ctx["public_base_url_configured"] = bool(cfg.public_base_url)
    ctx["error"] = None
    return templates.TemplateResponse(request=request, name="upload_links.html", context=ctx)


@router.post("/upload-links/{public_id}/rotate", response_class=HTMLResponse)
def owner_upload_links_rotate(
    public_id: str,
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    _summary, secret = svc.do_rotate_upload_link(db, public_id)
    links = svc.get_upload_links(db)
    ctx = _base(request, db)
    ctx["links"] = links
    ctx["new_secret"] = secret
    ctx["new_secret_full_url"] = svc.compose_public_upload_url(secret)
    ctx["public_base_url_configured"] = bool(get_settings().public_base_url)
    ctx["error"] = None
    return templates.TemplateResponse(request=request, name="upload_links.html", context=ctx)


@router.post("/upload-links/{public_id}/revoke", response_class=HTMLResponse)
def owner_upload_links_revoke(
    public_id: str,
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    svc.do_revoke_upload_link(db, public_id)
    return RedirectResponse(url="/owner/upload-links", status_code=303)


@router.post("/upload-links/{public_id}/delete", response_class=HTMLResponse)
def owner_upload_links_delete(
    public_id: str,
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    svc.do_delete_upload_link(db, public_id)
    return RedirectResponse(url="/owner/upload-links", status_code=303)
