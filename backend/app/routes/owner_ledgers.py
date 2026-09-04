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

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.network_boundary import require_owner_console_local
from app.routes.owner_console import _base
from app.routes.owner_console._shared import templates
from app.services import owner_console_service as svc
from app.version import BACKEND_VERSION  # noqa: F401  (kept for parity with sibling pages)

# CSRF 修复:复用 owner_console._shared 的共享 templates(已带 context_processors=[csrf_context]
# 与 owner_datetime filter)。此前本模块自建 Jinja2Templates 漏了 csrf_context,真实浏览器下
# 本页 POST 表单拿不到 <meta name="csrf-token">,会被 /owner CSRF 中间件 403(TestClient
# 豁免 CSRF 故没测出)。共享单实例后这类"自建漏 processor"隐患整类消除。


router = APIRouter(prefix="/owner", tags=["owner-console"])


def _require_local(request: Request) -> None:
    require_owner_console_local(request)


LocalOnly = Depends(_require_local)


def _render_ledgers_page(
    request: Request,
    db: Session,
    *,
    error: str | None = None,
    submitted_name: str | None = None,
) -> HTMLResponse:
    """Render the ledger management page (active + archived rows).

    Shared by the GET handler and the create/archive/unarchive error paths so
    every render shows the same surface and an optional error banner.
    """
    ctx = _base(request, db)
    ctx["ledger_rows"] = svc.list_manageable_console_ledgers(db)
    ctx["archived_rows"] = svc.list_archived_console_ledgers(db)
    ctx["error"] = error
    ctx["created_ledger"] = None
    ctx["submitted_name"] = submitted_name
    return templates.TemplateResponse(request=request, name="ledgers.html", context=ctx)


@router.get("/ledgers", response_class=HTMLResponse)
def owner_ledgers_get(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    return _render_ledgers_page(request, db)


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
        return _render_ledgers_page(request, db, error=exc.message, submitted_name=name)
    return RedirectResponse(url="/owner/ledgers", status_code=303)


@router.post("/ledgers/{ledger_id}/archive", response_class=HTMLResponse)
def owner_ledger_archive_post(
    request: Request,
    ledger_id: str,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Archive (reversible soft-delete) a ledger, then redirect back.

    The ledger disappears from every active surface but its data is kept; it
    can be restored from the "已归档账本" section. A rejected archive (e.g. the
    default ledger) re-renders the page with the reason so it isn't silent.
    """
    try:
        svc.do_archive_ledger(db, ledger_id=ledger_id)
    except AppError as exc:
        return _render_ledgers_page(request, db, error=exc.message)
    return RedirectResponse(url="/owner/ledgers", status_code=303)


@router.post("/ledgers/{ledger_id}/unarchive", response_class=HTMLResponse)
def owner_ledger_unarchive_post(
    request: Request,
    ledger_id: str,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Restore an archived ledger, then redirect back to the management page."""
    try:
        svc.do_unarchive_ledger(db, ledger_id=ledger_id)
    except AppError as exc:
        return _render_ledgers_page(request, db, error=exc.message)
    return RedirectResponse(url="/owner/ledgers", status_code=303)
