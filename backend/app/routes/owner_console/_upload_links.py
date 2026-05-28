"""Owner Console upload-link list + per-link actions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.routes.owner_console._shared import LocalOnly, _base, templates
from app.services import owner_console_service as svc

router = APIRouter(prefix="/owner", tags=["owner-console"])


def _parse_optional_int(raw: str | None) -> int | None:
    value = (raw or "").strip()
    if not value:
        return None
    return int(value)


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


@router.post("/upload-links/{public_id}/extend", response_class=HTMLResponse)
def owner_upload_links_extend(
    public_id: str,
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    svc.do_extend_upload_link(db, public_id)
    return RedirectResponse(url="/owner/upload-links", status_code=303)


@router.post("/upload-links/{public_id}/limits", response_class=HTMLResponse)
def owner_upload_links_limits(
    public_id: str,
    request: Request,
    daily_byte_budget: str | None = Form(default=None),
    per_remote_min_interval_seconds: int = Form(default=0),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    try:
        svc.do_update_upload_link_limits(
            db,
            public_id,
            daily_byte_budget=_parse_optional_int(daily_byte_budget),
            per_remote_min_interval_seconds=per_remote_min_interval_seconds,
        )
    except ValueError:
        ctx = _base(request, db)
        ctx["links"] = svc.get_upload_links(db)
        ctx["new_secret"] = None
        ctx["new_secret_full_url"] = None
        ctx["public_base_url_configured"] = bool(get_settings().public_base_url)
        ctx["error"] = "配额必须是非负整数；留空表示使用默认值。"
        return templates.TemplateResponse(
            request=request,
            name="upload_links.html",
            context=ctx,
            status_code=422,
        )
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
