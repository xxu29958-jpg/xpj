"""Owner Console upload-link list + per-link actions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.routes.owner_console._shared import LocalOnly, _base, templates
from app.services import owner_console_service as svc
from app.services.installation_health_service import (
    configured_mobile_endpoint_url,
    owner_recovery_message,
)

router = APIRouter(prefix="/owner", tags=["owner-console"])


def _parse_optional_int(raw: str | None) -> int | None:
    value = (raw or "").strip()
    if not value:
        return None
    return int(value)


def _render_upload_links(
    request: Request,
    db: Session,
    *,
    mobile_endpoint: str | None,
    links: list[svc.UploadLinkSummary] | None = None,
    secret: svc.UploadLinkSecret | None = None,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    ctx = _base(request, db)
    ctx["links"] = svc.get_upload_links(db) if links is None else links
    ctx["new_secret"] = secret
    ctx["new_secret_full_url"] = (
        svc.compose_public_upload_url(secret, public_base_url=mobile_endpoint)
        if secret is not None and mobile_endpoint is not None
        else None
    )
    ctx["public_base_url_configured"] = mobile_endpoint is not None
    ctx["error"] = error
    return templates.TemplateResponse(
        request=request,
        name="upload_links.html",
        context=ctx,
        status_code=status_code,
    )


@router.get("/upload-links", response_class=HTMLResponse)
def owner_upload_links_get(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    mobile_endpoint = configured_mobile_endpoint_url(get_settings().public_base_url)
    return _render_upload_links(request, db, mobile_endpoint=mobile_endpoint)


@router.post("/upload-links", response_class=HTMLResponse)
def owner_upload_links_create(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    cfg = get_settings()
    mobile_endpoint = configured_mobile_endpoint_url(cfg.public_base_url)
    ledger_id = svc.get_default_ledger_id(db)
    account_id = svc.get_owner_account_id(db)
    if ledger_id is None or account_id is None:
        return _render_upload_links(
            request,
            db,
            mobile_endpoint=mobile_endpoint,
            links=[],
            error=owner_recovery_message(cfg.owner_recovery_channel),
        )
    if mobile_endpoint is None:
        return _render_upload_links(
            request,
            db,
            mobile_endpoint=None,
            error="请先在设置中配置可供手机访问的 HTTPS 地址，再创建上传链接。",
        )
    tz = (cfg.ocr_default_timezone or "Asia/Shanghai").strip() or "Asia/Shanghai"
    _summary, secret = svc.do_create_upload_link(
        db, ledger_id=ledger_id, admin_account_id=account_id, default_timezone=tz
    )
    return _render_upload_links(request, db, mobile_endpoint=mobile_endpoint, secret=secret)


@router.post("/upload-links/{public_id}/rotate", response_class=HTMLResponse)
def owner_upload_links_rotate(
    public_id: str,
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    cfg = get_settings()
    mobile_endpoint = configured_mobile_endpoint_url(cfg.public_base_url)
    if svc.get_owner_account_id(db) is None:
        return _render_upload_links(
            request,
            db,
            mobile_endpoint=mobile_endpoint,
            links=[],
            error=owner_recovery_message(cfg.owner_recovery_channel),
        )
    if mobile_endpoint is None:
        return _render_upload_links(
            request,
            db,
            mobile_endpoint=None,
            error="请先在设置中配置可供手机访问的 HTTPS 地址，再重新生成上传链接。",
        )
    _summary, secret = svc.do_rotate_upload_link(db, public_id)
    return _render_upload_links(request, db, mobile_endpoint=mobile_endpoint, secret=secret)


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
        return _render_upload_links(
            request,
            db,
            mobile_endpoint=configured_mobile_endpoint_url(get_settings().public_base_url),
            error="配额必须是非负整数；留空表示使用默认值。",
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
