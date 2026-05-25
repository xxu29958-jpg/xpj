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

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.models import AlgorithmDecision
from app.routes.owner_console._ai_advisor import _owner_console_tenant_id
from app.routes.owner_console._shared import LocalOnly, _base, templates
from app.services.learning_service import (
    ALGORITHM_TYPES,
    get_status_overview,
    run_full_maintenance,
    set_decision_status,
)

router = APIRouter(prefix="/owner", tags=["owner-console"])

# How many recent active decisions to surface in the manual-dismiss
# table. 50 keeps the page snappy; if the owner has more than 50
# active rows they almost certainly need run-full-maintenance, not a
# row-by-row click.
_ACTIVE_PEEK_LIMIT = 50


def _recent_active_decisions(
    db: Session, *, tenant_id: str, limit: int = _ACTIVE_PEEK_LIMIT
) -> list[AlgorithmDecision]:
    return list(
        db.scalars(
            select(AlgorithmDecision)
            .where(AlgorithmDecision.tenant_id == tenant_id)
            .where(AlgorithmDecision.status == "active")
            .order_by(AlgorithmDecision.created_at.desc())
            .limit(limit)
        )
    )


@router.get("/learning-maintenance", response_class=HTMLResponse)
def owner_learning_maintenance_get(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    overview = get_status_overview(db)
    tenant_id = _owner_console_tenant_id(db)
    ctx = _base(request, db)
    ctx["overview"] = overview
    ctx["tenant_id"] = tenant_id
    ctx["active_decisions"] = _recent_active_decisions(
        db, tenant_id=tenant_id
    )
    # Pass the registry so the template can show display labels for
    # each algorithm type next to the raw decision_type identifier.
    ctx["algorithm_types"] = [
        ALGORITHM_TYPES[name] for name in sorted(ALGORITHM_TYPES)
    ]
    return templates.TemplateResponse(
        request=request,
        name="learning_maintenance.html",
        context=ctx,
    )


@router.post("/learning-maintenance/run", response_class=HTMLResponse)
def owner_learning_maintenance_run_post(
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    run_full_maintenance(db)
    return RedirectResponse(
        url="/owner/learning-maintenance", status_code=303
    )


@router.post(
    "/learning-maintenance/dismiss-decision", response_class=HTMLResponse
)
def owner_learning_maintenance_dismiss_post(
    decision_public_id: str = Form(...),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    tenant_id = _owner_console_tenant_id(db)
    decision = db.scalar(
        select(AlgorithmDecision)
        .where(AlgorithmDecision.tenant_id == tenant_id)
        .where(AlgorithmDecision.public_id == decision_public_id)
        .limit(1)
    )
    if decision is None:
        # No row → just redirect; the panel will show the up-to-date
        # state. We don't 404 because the owner might race a cleanup.
        return RedirectResponse(
            url="/owner/learning-maintenance", status_code=303
        )
    if decision.status != "active":
        # Already closed by another path; nothing to do.
        return RedirectResponse(
            url="/owner/learning-maintenance", status_code=303
        )
    # Owner-driven manual dismiss → 'dismissed' (not 'withdrawn',
    # which is reserved for algorithm-version rollback governance).
    set_decision_status(
        db,
        tenant_id=tenant_id,
        decision_id=decision.id,
        new_status="dismissed",
    )
    db.commit()
    return RedirectResponse(
        url="/owner/learning-maintenance", status_code=303
    )
