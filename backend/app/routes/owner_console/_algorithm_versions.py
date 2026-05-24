"""Owner Console algorithm-version governance."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.owner_console._ai_advisor import _owner_console_tenant_id
from app.routes.owner_console._shared import LocalOnly, _base, templates
from app.services.learning_service import (
    list_algorithm_versions,
    withdraw_algorithm_version,
)

router = APIRouter(prefix="/owner", tags=["owner-console"])


@router.get("/algorithm-versions", response_class=HTMLResponse)
def owner_algorithm_versions_get(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    tenant_id = _owner_console_tenant_id(db)
    ctx = _base(request, db)
    ctx["tenant_id"] = tenant_id
    ctx["versions"] = list_algorithm_versions(db, tenant_id=tenant_id)
    return templates.TemplateResponse(
        request=request,
        name="algorithm_versions.html",
        context=ctx,
    )


@router.post("/algorithm-versions/withdraw", response_class=HTMLResponse)
def owner_algorithm_versions_withdraw_post(
    decision_type: str = Form(...),
    algorithm_version: str = Form(...),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    tenant_id = _owner_console_tenant_id(db)
    withdraw_algorithm_version(
        db,
        tenant_id=tenant_id,
        decision_type=decision_type,
        algorithm_version=algorithm_version,
    )
    db.commit()
    return RedirectResponse(url="/owner/algorithm-versions", status_code=303)
