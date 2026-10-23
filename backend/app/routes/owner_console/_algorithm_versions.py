"""Owner Console algorithm-version governance."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.error_reporting import retain_handled_error
from app.errors import AppError
from app.routes.owner_console._shared import LocalOnly, _base, templates
from app.services import owner_console_service as svc
from app.services.learning_service import (
    ALGORITHM_TYPES,
    learning_activity,
    list_algorithm_versions,
    withdraw_algorithm_version,
)
from app.services.learning_service._policy import set_policy
from app.services.learning_service._withdrawal import withdraw_feedback

router = APIRouter(prefix="/owner", tags=["owner-console"])


def _render_versions(
    request: Request, db: Session, ledger_id: str | None = None,
    *, error: str | None = None, status_code: int = 200,
) -> HTMLResponse:
    choices, selected = svc.resolve_console_ledger_scope(db, ledger_id)
    ctx = _base(request, db)
    ctx.update(ledger_choices=choices, selected_ledger=selected, algorithm_types=ALGORITHM_TYPES, error=error)
    ctx["versions"] = list_algorithm_versions(db, tenant_id=selected.ledger_id) if selected else []
    ctx["activity"] = learning_activity(db, tenant_id=selected.ledger_id) if selected else None
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


@router.post("/algorithm-versions/policy", response_class=HTMLResponse)
def owner_algorithm_policy_post(request: Request, ledger_id: str = Form(...),
        decision_type: str = Form(...), algorithm_version: str = Form(...),
        axis: Literal["new_suggestions", "training"] = Form(...), enabled: bool = Form(...),
        _local: None = LocalOnly, db: Session = Depends(get_db)) -> Response:
    _, selected = svc.resolve_console_ledger_scope(db, ledger_id, mutation=True)
    versions = list_algorithm_versions(db, tenant_id=selected.ledger_id)
    if not any(row.decision_type == decision_type and row.algorithm_version == algorithm_version for row in versions):
        raise AppError("not_found", status_code=404)
    supported = ALGORITHM_TYPES.get(decision_type)
    if (decision_type not in {"category_suggestion", "duplicate_candidate", "recognition_time_choice", "recognition_field_choice", "repayment_choice"}
            or (axis == "new_suggestions" and (supported is None or supported.current_version != algorithm_version))):
        raise AppError("not_found", status_code=404)
    try:
        set_policy(db, tenant_id=selected.ledger_id, decision_type=decision_type,
            version=algorithm_version, axis=axis, enabled=enabled)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        retain_handled_error(request, exc)
        return _render_versions(request, db, selected.ledger_id, status_code=500,
            error="设置未能确认保存。请核对当前开关状态后重试。")
    return RedirectResponse("/owner/algorithm-versions?" + urlencode({"ledger_id": selected.ledger_id}) + "#algorithm-history", status_code=303)


@router.post("/algorithm-versions/withdraw-feedback", response_class=HTMLResponse)
def owner_feedback_withdraw_post(request: Request, ledger_id: str = Form(...), event_public_id: str = Form(...),
        _local: None = LocalOnly, db: Session = Depends(get_db)) -> Response:
    _, selected = svc.resolve_console_ledger_scope(db, ledger_id, mutation=True)
    try:
        withdraw_feedback(db, tenant_id=selected.ledger_id, public_id=event_public_id)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        retain_handled_error(request, exc)
        return _render_versions(request, db, selected.ledger_id, status_code=500,
            error="尚未确认这次选择是否已撤回。请核对下方反馈状态后重试。")
    return RedirectResponse("/owner/algorithm-versions?" + urlencode({"ledger_id": selected.ledger_id}) + "#learning-feedback", status_code=303)
