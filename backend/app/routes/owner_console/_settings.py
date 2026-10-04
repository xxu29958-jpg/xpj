"""Owner Console runtime-settings pages.

Owner-facing runtime controls and read-only host boundaries under
``/owner/settings`` in the shared local workspace.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.error_reporting import retain_handled_error
from app.routes.owner_console._shared import LocalOnly, _base, templates
from app.services import recognition_setup_service, route_inspector_service, runtime_settings_service

router = APIRouter(prefix="/owner", tags=["owner-console"])


def _settings_ctx(
    request: Request,
    db: Session,
    *,
    message: str | None = None,
    error: str | None = None,
) -> dict:
    ctx = _base(request, db)
    ctx["settings_view"] = runtime_settings_service.get_view()
    ctx["message"] = message
    ctx["error"] = error
    return ctx


@router.get("/settings", response_class=HTMLResponse)
def owner_settings_index(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    ctx = _settings_ctx(request, db)
    ctx["security_view"] = runtime_settings_service.get_security_view()
    return templates.TemplateResponse(request=request, name="settings/index.html", context=ctx)


@router.get("/settings/recognition", response_class=HTMLResponse)
def owner_settings_recognition_get(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    ctx = _settings_ctx(request, db)
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
    recognition_action: str = "save",
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
        if recognition_action == "save":
            recognition_view = runtime_settings_service.update_recognition_settings(form)
            check = recognition_setup_service.RecognitionCheck("识别设置已保存；下一次上传或手动识别即使用新配置，无需重启。")
        else:
            check = recognition_setup_service.inspect_connection(form, action=recognition_action)
            recognition_view = runtime_settings_service.get_recognition_view(form)
    except Exception as exc:  # noqa: BLE001 — validated error is rendered beside the preserved draft
        retain_handled_error(request, exc)
        error_status = getattr(exc, "status_code", 503)
        ctx = _settings_ctx(
            request,
            db,
            error=getattr(exc, "message", None) or "操作未完成，请检查输入或服务状态后重试。",
        )
        ctx["recognition_view"] = runtime_settings_service.get_recognition_view(form)
        ctx["recognition_action"] = recognition_action
        return templates.TemplateResponse(request=request, name="settings/recognition.html", context=ctx,
            status_code=200 if recognition_action == "save" and error_status < 500 else error_status)
    ctx = _settings_ctx(
        request,
        db,
        message=check.message,
    )
    ctx["recognition_view"] = recognition_view
    ctx["recognition_models"] = check.models
    ctx["recognition_action"] = recognition_action
    return templates.TemplateResponse(request=request, name="settings/recognition.html", context=ctx)


@router.get("/settings/public-base-url", response_class=HTMLResponse)
def owner_settings_public_base_url_get(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    ctx = _settings_ctx(request, db)
    return templates.TemplateResponse(request=request, name="settings/public_base_url.html", context=ctx)


def _post_public_base_url(
    request: Request,
    db: Session,
    public_base_url: str,
) -> HTMLResponse:
    try:
        runtime_settings_service.update_public_base_url(public_base_url)
    except Exception as exc:  # noqa: BLE001 — retain the draft beside the existing validated error
        retain_handled_error(request, exc)
        message = getattr(exc, "message", None) or "未能确认保存结果，请核对当前地址和主机设置存储后重试。"
        ctx = _settings_ctx(request, db, error=message)
        ctx["public_base_url_draft"] = public_base_url
        error_status = getattr(exc, "status_code", 503)
        return templates.TemplateResponse(request=request, name="settings/public_base_url.html", context=ctx,
            status_code=200 if error_status < 500 else error_status)
    ctx = _settings_ctx(
        request,
        db,
        message="已保存到受保护的运行时设置，下一次创建上传链接即生效。公网连接仍需单独检查。",
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
    recognition_action: str = Form("save"),
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
            recognition_action=recognition_action,
        )
    raise HTTPException(status_code=404)


@router.get("/settings/security", response_class=HTMLResponse)
def owner_settings_security(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    ctx = _settings_ctx(request, db)
    ctx["security_view"] = runtime_settings_service.get_security_view()
    return templates.TemplateResponse(request=request, name="settings/security.html", context=ctx)


@router.get("/settings/api", response_class=HTMLResponse)
def owner_settings_api(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    ctx = _settings_ctx(request, db)
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
    ctx = _settings_ctx(request, db)
    ctx["about_view"] = runtime_settings_service.get_about_view()
    return templates.TemplateResponse(request=request, name="settings/about.html", context=ctx)
