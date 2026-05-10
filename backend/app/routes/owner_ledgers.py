"""Owner Console — multi-ledger management page (v0.4-alpha1).

Split out of :mod:`app.routes.owner_console` to keep that file under the
recommended size budget. Like the rest of the Owner Console, every endpoint
is local-loopback only — Cloudflare Tunnel and other public hosts are
rejected by ``require_owner_console_local``.

Endpoints:
    GET  /owner/ledgers          — list ledgers + counts, "create new" form
    POST /owner/ledgers          — create a new ledger owned by the local
                                   owner account; redirects back to GET on
                                   success so reload-safe.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.network_boundary import require_owner_console_local
from app.routes.owner_console import _base, _format_owner_datetime
from app.services import owner_console_service as svc
from app.version import BACKEND_VERSION  # noqa: F401  (kept for parity with sibling pages)


_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates" / "owner"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
templates.env.filters["owner_datetime"] = _format_owner_datetime


router = APIRouter(prefix="/owner", tags=["owner-console"])


def _require_local(request: Request) -> None:
    require_owner_console_local(request)


LocalOnly = Depends(_require_local)


@router.get("/ledgers", response_class=HTMLResponse)
def owner_ledgers_get(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    rows = svc.list_console_ledgers(db)
    ctx = _base(request, db)
    ctx["ledger_rows"] = rows
    ctx["error"] = None
    ctx["created_ledger"] = None
    return templates.TemplateResponse(
        request=request, name="ledgers.html", context=ctx
    )


@router.post("/ledgers", response_class=HTMLResponse)
def owner_ledgers_post(
    request: Request,
    name: str = Form(...),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Create a new ledger and re-render the page.

    On validation errors (empty name, name too long, owner missing) we render
    the page with an error banner instead of redirecting so the form keeps
    its input. On success we redirect via 303 to GET so the form is reload
    safe (POST/Redirect/GET).
    """
    try:
        svc.do_create_ledger(db, name=name)
    except AppError as exc:
        ctx = _base(request, db)
        ctx["ledger_rows"] = svc.list_console_ledgers(db)
        ctx["error"] = exc.message
        ctx["created_ledger"] = None
        ctx["submitted_name"] = name
        return templates.TemplateResponse(
            request=request, name="ledgers.html", context=ctx
        )
    return RedirectResponse(url="/owner/ledgers", status_code=303)
