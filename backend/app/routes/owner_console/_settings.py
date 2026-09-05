"""Owner Console runtime-settings pages.

Owner-facing runtime controls and read-only host boundaries under
``/owner/settings``. The sub-nav is rendered from ``_SETTINGS_NAV``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.owner_console._shared import LocalOnly, _base, templates
from app.services import route_inspector_service, runtime_settings_service

router = APIRouter(prefix="/owner", tags=["owner-console"])


_SETTINGS_NAV = (
    {"slug": "", "label": "概览", "url": "/owner/settings"},
    {"slug": "recognition", "label": "识别与录入", "url": "/owner/settings/recognition"},
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
    return templates.TemplateResponse(request=request, name="settings/index.html", context=ctx)


@router.get("/settings/recognition", response_class=HTMLResponse)
def owner_settings_recognition_get(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    ctx = _settings_ctx(request, db, active="recognition")
    ctx["recognition_view"] = runtime_settings_service.get_recognition_view()
    return templates.TemplateResponse(request=request, name="settings/recognition.html", context=ctx)


def _post_recognition_settings(
    request: Request,
    db: Session,
    *,
    ocr_provider: str,
    ocr_auto_run: bool,
    ocr_fallback_provider: str,
    ocr_min_confidence: str,
    ocr_default_timezone: str,
    local_llm_base_url: str,
    local_llm_model: str,
    local_llm_timeout_seconds: str,
    local_llm_max_concurrent: str,
    local_llm_queue_timeout_seconds: str,
    debt_bill_provider: str,
) -> HTMLResponse:
    form = runtime_settings_service.RecognitionSettingsForm(
        ocr_provider=ocr_provider,
        ocr_auto_run=ocr_auto_run,
        ocr_fallback_provider=ocr_fallback_provider,
        ocr_min_confidence=ocr_min_confidence,
        ocr_default_timezone=ocr_default_timezone,
        local_llm_base_url=local_llm_base_url,
        local_llm_model=local_llm_model,
        local_llm_timeout_seconds=local_llm_timeout_seconds,
        local_llm_max_concurrent=local_llm_max_concurrent,
        local_llm_queue_timeout_seconds=local_llm_queue_timeout_seconds,
        debt_bill_provider=debt_bill_provider,
    )
    try:
        recognition_view = runtime_settings_service.update_recognition_settings(form)
    except Exception as exc:  # noqa: BLE001 — validated error is rendered beside the preserved draft
        ctx = _settings_ctx(
            request,
            db,
            active="recognition",
            error=getattr(exc, "message", None) or "保存失败，请检查输入。",
        )
        ctx["recognition_view"] = runtime_settings_service.get_recognition_view(form)
        return templates.TemplateResponse(request=request, name="settings/recognition.html", context=ctx)
    ctx = _settings_ctx(
        request,
        db,
        active="recognition",
        message="识别设置已保存；下一次上传或手动识别即使用新配置，无需重启。",
    )
    ctx["recognition_view"] = recognition_view
    return templates.TemplateResponse(request=request, name="settings/recognition.html", context=ctx)


@router.get("/settings/public-base-url", response_class=HTMLResponse)
def owner_settings_public_base_url_get(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    ctx = _settings_ctx(request, db, active="public-base-url")
    return templates.TemplateResponse(request=request, name="settings/public_base_url.html", context=ctx)


def _post_public_base_url(
    request: Request,
    db: Session,
    public_base_url: str,
) -> HTMLResponse:
    try:
        runtime_settings_service.update_public_base_url(public_base_url)
    except Exception as exc:  # noqa: BLE001 — surfaced to UI via getattr(exc, "message", ...)
        message = getattr(exc, "message", None) or "保存失败，请检查输入。"
        ctx = _settings_ctx(request, db, active="public-base-url", error=message)
        return templates.TemplateResponse(request=request, name="settings/public_base_url.html", context=ctx)
    ctx = _settings_ctx(
        request,
        db,
        active="public-base-url",
        message="已保存到受保护的运行时设置，下一次创建上传链接即生效。",
    )
    return templates.TemplateResponse(request=request, name="settings/public_base_url.html", context=ctx)


@router.post("/settings/{settings_group}", response_class=HTMLResponse)
def owner_settings_post(
    settings_group: str,
    request: Request,
    public_base_url: str = Form(""),
    ocr_provider: str = Form("empty"),
    ocr_auto_run: bool = Form(False),
    ocr_fallback_provider: str = Form("empty"),
    ocr_min_confidence: str = Form("0.65"),
    ocr_default_timezone: str = Form("Asia/Shanghai"),
    local_llm_base_url: str = Form(""),
    local_llm_model: str = Form(""),
    local_llm_timeout_seconds: str = Form("60"),
    local_llm_max_concurrent: str = Form("2"),
    local_llm_queue_timeout_seconds: str = Form("5"),
    debt_bill_provider: str = Form("empty"),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if settings_group == "public-base-url":
        return _post_public_base_url(request, db, public_base_url)
    if settings_group == "recognition":
        return _post_recognition_settings(
            request,
            db,
            ocr_provider=ocr_provider,
            ocr_auto_run=ocr_auto_run,
            ocr_fallback_provider=ocr_fallback_provider,
            ocr_min_confidence=ocr_min_confidence,
            ocr_default_timezone=ocr_default_timezone,
            local_llm_base_url=local_llm_base_url,
            local_llm_model=local_llm_model,
            local_llm_timeout_seconds=local_llm_timeout_seconds,
            local_llm_max_concurrent=local_llm_max_concurrent,
            local_llm_queue_timeout_seconds=local_llm_queue_timeout_seconds,
            debt_bill_provider=debt_bill_provider,
        )
    raise HTTPException(status_code=404)


@router.get("/settings/security", response_class=HTMLResponse)
def owner_settings_security(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    ctx = _settings_ctx(request, db, active="security")
    ctx["security_view"] = runtime_settings_service.get_security_view()
    return templates.TemplateResponse(request=request, name="settings/security.html", context=ctx)


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
    return templates.TemplateResponse(request=request, name="settings/api.html", context=ctx)


@router.get("/settings/about", response_class=HTMLResponse)
def owner_settings_about(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    ctx = _settings_ctx(request, db, active="about")
    ctx["about_view"] = runtime_settings_service.get_about_view()
    return templates.TemplateResponse(request=request, name="settings/about.html", context=ctx)
