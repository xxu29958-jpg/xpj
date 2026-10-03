"""Owner Console v1.2 learning-layer maintenance panel.

Surfaces:

* ``GET /owner/learning-maintenance`` — read-only snapshot: per-table
  row count, expired-but-not-yet-pruned candidate count, active
  decision count, stale-active candidate count, last cleanup time,
  and the most recent active decisions (so the owner has something
  concrete to dismiss).
* ``POST /owner/learning-maintenance/run`` — manual trigger. Calls
  :func:`learning_service.run_full_maintenance`.
* ``POST /owner/learning-maintenance/dismiss-decision`` — flip ONE
  active decision to ``status='dismissed'``. Used when an algorithm
  produces an obviously-wrong suggestion the user hasn't yet seen;
  letting the owner pre-emptively dismiss saves the user from being
  shown bad advice.

POST paths redirect back to GET so the owner always sees fresh
counts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
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
    find_decision_by_public_id,
    get_status_overview,
    list_recent_active_decisions,
    run_full_maintenance,
    set_decision_status,
)

if TYPE_CHECKING:
    from app.models import AlgorithmDecision

router = APIRouter(prefix="/owner", tags=["owner-console"])

# How many recent active decisions to surface in the manual-dismiss
# table. 50 keeps the page snappy; if the owner has more than 50
# active rows they almost certainly need run-full-maintenance, not a
# row-by-row click.
_ACTIVE_PEEK_LIMIT = 50


def _recent_active_decisions(
    db: Session, *, tenant_id: str, limit: int = _ACTIVE_PEEK_LIMIT
) -> list[AlgorithmDecision]:
    return list_recent_active_decisions(db, tenant_id=tenant_id, limit=limit)


def _render_maintenance(
    request: Request, db: Session, ledger_id: str | None = None,
    *, error: str | None = None, active_section: str | None = None,
    error_decision_public_id: str | None = None, status_code: int = 200,
) -> HTMLResponse:
    choices, selected = svc.resolve_console_ledger_scope(db, ledger_id)
    ctx = _base(request, db)
    ctx.update(ledger_choices=choices, selected_ledger=selected, error=error, active_section=active_section)
    ctx["error_decision_public_id"] = error_decision_public_id
    ctx["overview"] = get_status_overview(db, tenant_id=selected.ledger_id) if selected else None
    ctx["active_decisions"] = _recent_active_decisions(db, tenant_id=selected.ledger_id) if selected else []
    ctx["algorithm_types"] = ALGORITHM_TYPES
    return templates.TemplateResponse(
        request=request,
        name="learning_maintenance.html",
        context=ctx,
        status_code=status_code,
    )


@router.get("/learning-maintenance", response_class=HTMLResponse)
def owner_learning_maintenance_get(
    request: Request, ledger_id: str | None = None,
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> HTMLResponse:
    return _render_maintenance(request, db, ledger_id)


@router.post("/learning-maintenance/run", response_class=HTMLResponse)
def owner_learning_maintenance_run_post(
    request: Request,
    ledger_id: str | None = Form(None),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    _, selected = svc.resolve_console_ledger_scope(db, ledger_id, mutation=True)
    assert selected is not None
    try:
        run_full_maintenance(db, tenant_id=selected.ledger_id)
    except SQLAlchemyError as exc:
        db.rollback()
        retain_handled_error(request, exc)
        return _render_maintenance(request, db, selected.ledger_id, status_code=500, active_section="volume",
            error="未能确认本次维护结果，部分批次可能已经完成。请核对下方数量和上次完成记录，再决定是否继续。")
    return RedirectResponse(
        url="/owner/learning-maintenance?" + urlencode({"ledger_id": selected.ledger_id}) + "#learning-volume", status_code=303
    )


@router.post(
    "/learning-maintenance/dismiss-decision", response_class=HTMLResponse
)
def owner_learning_maintenance_dismiss_post(
    request: Request,
    decision_public_id: str = Form(...),
    ledger_id: str | None = Form(None),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    _, selected = svc.resolve_console_ledger_scope(db, ledger_id, mutation=True)
    assert selected is not None
    try:
        decision = find_decision_by_public_id(
            db, tenant_id=selected.ledger_id, public_id=decision_public_id
        )
        if decision is not None and decision.status == "active":
            set_decision_status(db, tenant_id=selected.ledger_id, decision_id=decision.id, new_status="dismissed")
            db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        retain_handled_error(request, exc)
        return _render_maintenance(request, db, selected.ledger_id, status_code=500, active_section="candidates",
            error_decision_public_id=decision_public_id,
            error="未能确认忽略结果。请先核对当前待采纳建议，再决定是否重试。")
    return RedirectResponse(
        url="/owner/learning-maintenance?" + urlencode({"ledger_id": selected.ledger_id}) + "#learning-candidates", status_code=303
    )
