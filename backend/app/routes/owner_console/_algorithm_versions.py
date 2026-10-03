"""Owner Console algorithm-version governance."""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import retain_handled_error
from app.routes.owner_console._shared import LocalOnly, _base, templates
from app.services import owner_console_service as svc
from app.services.learning_service import (
    ALGORITHM_TYPES,
    list_algorithm_versions,
    withdraw_algorithm_version,
)

router = APIRouter(prefix="/owner", tags=["owner-console"])


def _render_versions(
    request: Request, db: Session, ledger_id: str | None = None,
    *, error: str | None = None, status_code: int = 200,
) -> HTMLResponse:
    choices, selected = svc.resolve_console_ledger_scope(db, ledger_id)
    ctx = _base(request, db)
    ctx.update(ledger_choices=choices, selected_ledger=selected, algorithm_types=ALGORITHM_TYPES, error=error)
    ctx["versions"] = list_algorithm_versions(db, tenant_id=selected.ledger_id) if selected else []
    return templates.TemplateResponse(
        request=request,
        name="algorithm_versions.html",
        context=ctx,
        status_code=status_code,
    )


@router.get("/algorithm-versions", response_class=HTMLResponse)
def owner_algorithm_versions_get(
    request: Request, ledger_id: str | None = None,
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> HTMLResponse:
    return _render_versions(request, db, ledger_id)


@router.post("/algorithm-versions/withdraw", response_class=HTMLResponse)
def owner_algorithm_versions_withdraw_post(
    request: Request,
    decision_type: str = Form(...),
    algorithm_version: str = Form(...),
    ledger_id: str | None = Form(None),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    _, selected = svc.resolve_console_ledger_scope(db, ledger_id, mutation=True)
    assert selected is not None
    try:
        withdraw_algorithm_version(
            db, tenant_id=selected.ledger_id, decision_type=decision_type, algorithm_version=algorithm_version,
        )
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        retain_handled_error(request, exc)
        return _render_versions(request, db, selected.ledger_id, status_code=500,
            error="未能确认撤回结果。请先核对下方各版本的当前建议数量，再决定是否重试。")
    return RedirectResponse(
        url="/owner/algorithm-versions?" + urlencode({"ledger_id": selected.ledger_id}) + "#algorithm-history",
        status_code=303,
    )
