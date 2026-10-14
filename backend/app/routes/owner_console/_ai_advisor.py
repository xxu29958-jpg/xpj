"""Owner Console AI advisor status and confirmation panel."""

from __future__ import annotations

from dataclasses import replace
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.errors import AppError
from app.routes.owner_console._settings import _settings_ctx
from app.routes.owner_console._shared import LocalOnly, templates
from app.services import integration_settings_service as integration
from app.services import owner_console_service as svc
from app.services.budget_advisor_service import (
    advisor_status_for_tenant,
    recent_audit_rows,
)

router = APIRouter(prefix="/owner", tags=["owner-console"])


def _render_advisor(
    request: Request,
    db: Session,
    *,
    form: integration.AdvisorSettingsForm | None = None,
    message: str | None = None,
    error: str | None = None,
    status_code: int = 200,
    models: tuple[str, ...] = (),
    setup_step: str | None = None,
) -> HTMLResponse:
    settings = get_settings()
    choices, selected = svc.resolve_console_ledger_scope(db, request.query_params.get("ledger_id"))
    tenant_id = selected.ledger_id if selected else None
    ctx = _settings_ctx(request, db, message=message, error=error)
    ctx.update(ledger_choices=choices, selected_ledger=selected)
    ctx["ledger_query"] = "?" + urlencode({"ledger_id": tenant_id}) if tenant_id is not None else ""
    ctx["tenant_id"] = tenant_id
    ctx["status"] = advisor_status_for_tenant(db, tenant_id=tenant_id)
    ctx["audit_rows"] = recent_audit_rows(db, tenant_id=tenant_id, limit=10) if tenant_id is not None else []
    ctx["advisor_display_url"] = integration.display_advisor_url
    ctx["advisor_form"] = replace(form, base_url=integration.display_advisor_url(form.base_url)) if form else integration.advisor_form(settings)
    ctx["advisor_mode"] = ctx["advisor_form"].connection_mode or (
        "empty" if ctx["advisor_form"].provider == "empty" else
        "local" if integration.resolve_local_llm_base_url(ctx["advisor_form"].base_url) else "cloud")
    ctx["advisor_key_configured"] = bool(settings.budget_advisor_api_key)
    ctx["advisor_draft"] = form is not None
    ctx["advisor_saved_base_url"] = integration.display_advisor_url(settings.budget_advisor_base_url)
    ctx["advisor_saved_model"] = settings.budget_advisor_model
    ctx["advisor_connection_revision"] = integration.advisor_connection_revision(settings)
    ctx["advisor_models"] = models
    ctx["setup_step"] = setup_step
    return templates.TemplateResponse(
        request=request,
        name="ai_advisor.html",
        context=ctx,
        status_code=status_code,
    )


@router.get("/ai-advisor", response_class=HTMLResponse)
def owner_ai_advisor_get(request: Request, _local: None = LocalOnly, db: Session = Depends(get_db)) -> HTMLResponse:
    return _render_advisor(request, db)


@router.post("/ai-advisor/settings", response_class=HTMLResponse)
def owner_ai_advisor_settings_post(
    request: Request,
    provider: str = Form("empty"), base_url: str = Form(""), model: str = Form(""),
    api_key: str = Form(""), key_action: str = Form("auto"), clear_key: bool = Form(False),
    advisor_action: str = Form("save"),
    connection_mode: str = Form(""),
    timeout_seconds: str = Form("60"), min_interval_seconds: str = Form("60"), daily_call_limit: str = Form("50"),
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> Response:
    svc.resolve_console_ledger_scope(db, request.query_params.get("ledger_id"))
    if connection_mode:
        provider = "empty" if connection_mode == "empty" else "openai_compat"
    form = integration.AdvisorSettingsForm(provider, base_url, model, timeout_seconds, min_interval_seconds, daily_call_limit, connection_mode)
    key_action = "clear" if clear_key else key_action
    try:
        if advisor_action == "models":
            models = integration.read_advisor_models(form, api_key=api_key, key_action=key_action)
            message = f"已读取 {len(models)} 个模型，请选择后保存。尚未改动设置。"
            if "application/json" in request.headers.get("accept", ""):
                return JSONResponse({"models": models, "message": message})
            return _render_advisor(request, db, form=form, models=models, message=message,
                                   setup_step="connection")
        integration.save_advisor(form, api_key=api_key, key_action=key_action)
    except AppError as exc:
        if advisor_action == "models" and "application/json" in request.headers.get("accept", ""):
            return JSONResponse({"error": exc.message}, status_code=exc.status_code)
        return _render_advisor(request, db, form=form, error=exc.message, status_code=exc.status_code, setup_step="connection")
    return _render_advisor(request, db, message="连接已保存。下一步核对发送范围，再允许并测试。" if provider != "empty" else "AI 已关闭，月度安排继续使用本地预算规则。", setup_step="permission")


@router.post("/ai-advisor/test", response_class=HTMLResponse)
def owner_ai_advisor_test(request: Request, _local: None = LocalOnly, db: Session = Depends(get_db)) -> HTMLResponse:
    svc.resolve_console_ledger_scope(db, request.query_params.get("ledger_id"))
    try:
        message = integration.test_advisor_connection()
    except AppError as exc:
        return _render_advisor(request, db, error=exc.message, status_code=exc.status_code)
    return _render_advisor(request, db, message=message)


@router.post("/ai-advisor/confirmation", response_class=HTMLResponse)
def owner_ai_advisor_confirmation_post(
    request: Request,
    _local: None = LocalOnly,
    confirmed: str | None = Form(default=None),
    connection_revision: str = Form(""),
    action: str = Form("save"),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    _, selected = svc.resolve_console_ledger_scope(db, request.query_params.get("ledger_id"))
    try:
        if action == "test" and confirmed not in {"1", "true", "on", "yes"}:
            raise AppError("validation_error", "请勾选允许当前模型接收请求，再测试；也可保持关闭，使用本地预算规则。", status_code=422)
        integration.confirm_advisor(confirmed=confirmed in {"1", "true", "on", "yes"}, revision=connection_revision)
        if action == "test":
            message = integration.test_advisor_connection()
            return _render_advisor(request, db, message=message, setup_step="use")
    except AppError as exc:
        return _render_advisor(request, db, error=exc.message, status_code=exc.status_code, setup_step="permission")
    query = "?" + urlencode({"ledger_id": selected.ledger_id}) if selected else ""
    return RedirectResponse(url="/owner/ai-advisor" + query, status_code=303)
