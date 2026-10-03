"""Owner Console algorithm-version governance."""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.owner_console._shared import LocalOnly, _base, templates
from app.services import owner_console_service as svc
from app.services.learning_service import (
    list_algorithm_versions,
    withdraw_algorithm_version,
)

router = APIRouter(prefix="/owner", tags=["owner-console"])


@router.get("/algorithm-versions", response_class=HTMLResponse)
def owner_algorithm_versions_get(
    request: Request,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    choices, selected = svc.resolve_console_ledger_scope(db, ledger_id)
    ctx = _base(request, db)
    ctx.update(ledger_choices=choices, selected_ledger=selected)
    ctx["versions"] = list_algorithm_versions(db, tenant_id=selected.ledger_id) if selected else []
    return templates.TemplateResponse(
        request=request,
        name="algorithm_versions.html",
        context=ctx,
    )


@router.post("/algorithm-versions/withdraw", response_class=HTMLResponse)
def owner_algorithm_versions_withdraw_post(
    decision_type: str = Form(...),
    algorithm_version: str = Form(...),
    ledger_id: str | None = Form(None),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    _, selected = svc.resolve_console_ledger_scope(db, ledger_id, mutation=True)
    assert selected is not None
    withdraw_algorithm_version(
        db,
        tenant_id=selected.ledger_id,
        decision_type=decision_type,
        algorithm_version=algorithm_version,
    )
    db.commit()
    return RedirectResponse(url="/owner/algorithm-versions?" + urlencode({"ledger_id": selected.ledger_id}), status_code=303)
