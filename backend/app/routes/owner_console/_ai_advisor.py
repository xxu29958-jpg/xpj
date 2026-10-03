"""Owner Console AI advisor status and confirmation panel."""

from __future__ import annotations

from dataclasses import replace
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
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
    ctx["advisor_form"] = replace(form, base_url=integration.display_advisor_url(form.base_url)) if form else integration.advisor_form(settings)
    ctx["advisor_key_configured"] = bool(settings.budget_advisor_api_key)
    ctx["advisor_saved_base_url"] = integration.display_advisor_url(settings.budget_advisor_base_url)
    ctx["advisor_saved_model"] = settings.budget_advisor_model
    ctx["advisor_connection_revision"] = integration.advisor_connection_revision(settings)
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
    api_key: str = Form(""), key_action: str = Form("keep"),
    timeout_seconds: str = Form("60"), min_interval_seconds: str = Form("60"), daily_call_limit: str = Form("50"),
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> HTMLResponse:
    svc.resolve_console_ledger_scope(db, request.query_params.get("ledger_id"))
    form = integration.AdvisorSettingsForm(provider, base_url, model, timeout_seconds, min_interval_seconds, daily_call_limit)
    try:
        integration.save_advisor(form, api_key=api_key, key_action=key_action)
    except AppError as exc:
        return _render_advisor(request, db, form=form, error=exc.message, status_code=exc.status_code)
    return _render_advisor(request, db, message="模型设置已保存并生效。更换连接后，请在下方核对并允许请求，再测试模型。")


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
    db: Session = Depends(get_db),
) -> HTMLResponse:
    _, selected = svc.resolve_console_ledger_scope(db, request.query_params.get("ledger_id"))
    try:
        integration.confirm_advisor(confirmed=confirmed in {"1", "true", "on", "yes"}, revision=connection_revision)
    except AppError as exc:
        return _render_advisor(request, db, error=exc.message, status_code=exc.status_code)
    query = "?" + urlencode({"ledger_id": selected.ledger_id}) if selected else ""
    return RedirectResponse(url="/owner/ai-advisor" + query, status_code=303)
