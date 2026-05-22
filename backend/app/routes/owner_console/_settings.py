"""Owner Console runtime-settings pages.

Five endpoints under /owner/settings: index, public-base-url (GET/POST),
security, api, about. The sub-nav is rendered from ``_SETTINGS_NAV``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.owner_console._shared import LocalOnly, _base, templates
from app.services import route_inspector_service, runtime_settings_service

router = APIRouter(prefix="/owner", tags=["owner-console"])


_SETTINGS_NAV = (
    {"slug": "", "label": "概览", "url": "/owner/settings"},
    {"slug": "public-base-url", "label": "公网域名", "url": "/owner/settings/public-base-url"},
    {"slug": "security", "label": "安全 / 边界", "url": "/owner/settings/security"},
    {"slug": "api", "label": "接口一览", "url": "/owner/settings/api"},
    {"slug": "about", "label": "关于", "url": "/owner/settings/about"},
)


def _settings_ctx(
    request: Request,
    db: Session,
    *,
    active: str = "",
    message: str | None = None,
    error: str | None = None,
) -> dict:
    ctx = _base(request, db)
    ctx["settings_view"] = runtime_settings_service.get_view()
    ctx["settings_nav"] = _SETTINGS_NAV
    ctx["settings_active"] = active
    ctx["message"] = message
    ctx["error"] = error
    return ctx


@router.get("/settings", response_class=HTMLResponse)
def owner_settings_index(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    ctx = _settings_ctx(request, db, active="")
    ctx["security_view"] = runtime_settings_service.get_security_view()
    return templates.TemplateResponse(
        request=request, name="settings/index.html", context=ctx
    )


@router.get("/settings/public-base-url", response_class=HTMLResponse)
def owner_settings_public_base_url_get(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    ctx = _settings_ctx(request, db, active="public-base-url")
    return templates.TemplateResponse(
        request=request, name="settings/public_base_url.html", context=ctx
    )


@router.post("/settings/public-base-url", response_class=HTMLResponse)
def owner_settings_set_public_base_url(
    request: Request,
    public_base_url: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    try:
        runtime_settings_service.update_public_base_url(public_base_url)
    except Exception as exc:  # noqa: BLE001 — surfaced to UI via getattr(exc, "message", ...)
        message = getattr(exc, "message", None) or "保存失败，请检查输入。"
        ctx = _settings_ctx(request, db, active="public-base-url", error=message)
        return templates.TemplateResponse(
            request=request, name="settings/public_base_url.html", context=ctx
        )
    ctx = _settings_ctx(
        request,
        db,
        active="public-base-url",
        message="已保存到 backend/.env，下一次创建上传链接即生效。",
    )
    return templates.TemplateResponse(
        request=request, name="settings/public_base_url.html", context=ctx
    )


@router.get("/settings/security", response_class=HTMLResponse)
def owner_settings_security(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    ctx = _settings_ctx(request, db, active="security")
    ctx["security_view"] = runtime_settings_service.get_security_view()
    return templates.TemplateResponse(
        request=request, name="settings/security.html", context=ctx
    )


@router.get("/settings/api", response_class=HTMLResponse)
def owner_settings_api(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    ctx = _settings_ctx(request, db, active="api")
    groups = route_inspector_service.list_route_groups(request.app)
    ctx["route_groups"] = groups
    ctx["route_total"] = route_inspector_service.count_routes(groups)
    return templates.TemplateResponse(
        request=request, name="settings/api.html", context=ctx
    )


@router.get("/settings/about", response_class=HTMLResponse)
def owner_settings_about(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    ctx = _settings_ctx(request, db, active="about")
    ctx["about_view"] = runtime_settings_service.get_about_view()
    return templates.TemplateResponse(
        request=request, name="settings/about.html", context=ctx
    )
