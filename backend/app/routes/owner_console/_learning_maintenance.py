"""Owner Console v1.2 learning-layer maintenance panel.

Two surfaces:

* ``GET /owner/learning-maintenance`` — read-only snapshot: per-table
  row count, expired-but-not-yet-pruned candidate count, active
  decision count, stale-active candidate count, last cleanup time.
* ``POST /owner/learning-maintenance/run`` — manual trigger. Calls
  :func:`learning_service.run_full_maintenance`, which sweeps stale
  active rows then prunes expired ones, then stamps ``app_meta``
  with the run timestamp.

The post path redirects back to GET so the owner sees fresh counts.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.owner_console._shared import LocalOnly, _base, templates
from app.services.learning_service import (
    ALGORITHM_TYPES,
    get_status_overview,
    run_full_maintenance,
)

router = APIRouter(prefix="/owner", tags=["owner-console"])


@router.get("/learning-maintenance", response_class=HTMLResponse)
def owner_learning_maintenance_get(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    overview = get_status_overview(db)
    ctx = _base(request, db)
    ctx["overview"] = overview
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
