"""Owner Console AI advisor status and confirmation panel."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.owner_console._shared import LocalOnly, _base, templates
from app.services import owner_console_service as svc
from app.services import runtime_settings_service
from app.services.budget_advisor_service import (
    advisor_status_for_tenant,
    recent_audit_rows,
)
from app.tenants import DEFAULT_TENANT_ID

router = APIRouter(prefix="/owner", tags=["owner-console"])


def _owner_console_tenant_id(db: Session) -> str:
    return svc.get_default_ledger_id(db) or DEFAULT_TENANT_ID


@router.get("/ai-advisor", response_class=HTMLResponse)
def owner_ai_advisor_get(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    tenant_id = _owner_console_tenant_id(db)
    ctx = _base(request, db)
    ctx["tenant_id"] = tenant_id
    ctx["status"] = advisor_status_for_tenant(db, tenant_id=tenant_id)
    ctx["audit_rows"] = recent_audit_rows(db, tenant_id=tenant_id, limit=10)
    return templates.TemplateResponse(
        request=request,
        name="ai_advisor.html",
        context=ctx,
    )


@router.post("/ai-advisor/confirmation", response_class=HTMLResponse)
def owner_ai_advisor_confirmation_post(
    _local: None = LocalOnly,
    confirmed: str | None = Form(default=None),
) -> RedirectResponse:
    runtime_settings_service.update_budget_advisor_owner_confirmed(confirmed in {"1", "true", "on", "yes"})
    return RedirectResponse(url="/owner/ai-advisor", status_code=303)
