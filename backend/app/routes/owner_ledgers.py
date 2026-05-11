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
from app.services import invitation_service
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


# ---------------------------------------------------------------------------
# v0.4-beta1 — Family-ledger members & invitations management page.
#
# Owner Console mints / lists / revokes invitations through this UI without
# requiring the operator to hold a Bearer token. The page is local-loopback
# only; public hosts are rejected by ``require_owner_console_local`` so
# invite_token plain values never traverse the tunnel.
# ---------------------------------------------------------------------------


@router.get("/ledgers/{ledger_id}/members", response_class=HTMLResponse)
def owner_ledger_members_get(
    request: Request,
    ledger_id: str,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    ctx = _base(request, db)
    ctx["ledger_id"] = ledger_id
    ctx["ledger_name"] = _ledger_name(db, ledger_id)
    if ctx["ledger_name"] is None:
        ctx["error"] = "账本不存在或已归档。"
        ctx["members"] = []
        ctx["invitations"] = []
        ctx["new_invitation_token"] = None
        return templates.TemplateResponse(
            request=request, name="ledger_members.html", context=ctx
        )
    owner_id = svc.get_owner_account_id(db)
    ctx["members"] = invitation_service.list_members(
        db, ledger_id=ledger_id, requester_account_id=owner_id or 0
    )
    ctx["invitations"] = invitation_service.list_invitations(db, ledger_id=ledger_id)
    ctx["error"] = None
    ctx["new_invitation_token"] = None
    return templates.TemplateResponse(
        request=request, name="ledger_members.html", context=ctx
    )


@router.post("/ledgers/{ledger_id}/invitations", response_class=HTMLResponse)
def owner_ledger_invite_post(
    request: Request,
    ledger_id: str,
    role: str = Form(...),
    note: str | None = Form(default=None),
    ttl_days: int = Form(default=7),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    owner_id = svc.get_owner_account_id(db)
    if owner_id is None:
        raise AppError("server_error", status_code=500)
    try:
        result = invitation_service.create_invitation(
            db,
            ledger_id=ledger_id,
            role=role,
            created_by_account_id=owner_id,
            note=note,
            ttl_days=ttl_days,
        )
    except AppError as exc:
        ctx = _base(request, db)
        ctx["ledger_id"] = ledger_id
        ctx["ledger_name"] = _ledger_name(db, ledger_id)
        ctx["members"] = invitation_service.list_members(
            db, ledger_id=ledger_id, requester_account_id=owner_id
        )
        ctx["invitations"] = invitation_service.list_invitations(db, ledger_id=ledger_id)
        ctx["error"] = exc.message
        ctx["new_invitation_token"] = None
        return templates.TemplateResponse(
            request=request, name="ledger_members.html", context=ctx
        )
    ctx = _base(request, db)
    ctx["ledger_id"] = ledger_id
    ctx["ledger_name"] = _ledger_name(db, ledger_id)
    ctx["members"] = invitation_service.list_members(
        db, ledger_id=ledger_id, requester_account_id=owner_id
    )
    ctx["invitations"] = invitation_service.list_invitations(db, ledger_id=ledger_id)
    ctx["error"] = None
    ctx["new_invitation_token"] = result.invite_token
    return templates.TemplateResponse(
        request=request, name="ledger_members.html", context=ctx
    )


@router.post(
    "/ledgers/{ledger_id}/invitations/{public_id}/revoke",
    response_class=HTMLResponse,
)
def owner_ledger_invite_revoke_post(
    ledger_id: str,
    public_id: str,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        invitation_service.revoke_invitation(db, ledger_id=ledger_id, public_id=public_id)
    except AppError:
        # Idempotent UI: ignore unknown/already-revoked.
        pass
    return RedirectResponse(url=f"/owner/ledgers/{ledger_id}/members", status_code=303)


@router.post(
    "/ledgers/{ledger_id}/members/{member_id}/disable",
    response_class=HTMLResponse,
)
def owner_ledger_member_disable_post(
    request: Request,
    ledger_id: str,
    member_id: int,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    owner_id = svc.get_owner_account_id(db)
    if owner_id is None:
        raise AppError("server_error", status_code=500)
    try:
        invitation_service.disable_member(
            db,
            ledger_id=ledger_id,
            member_id=member_id,
            requester_account_id=owner_id,
        )
    except AppError as exc:
        ctx = _base(request, db)
        ctx["ledger_id"] = ledger_id
        ctx["ledger_name"] = _ledger_name(db, ledger_id)
        ctx["members"] = invitation_service.list_members(
            db, ledger_id=ledger_id, requester_account_id=owner_id
        )
        ctx["invitations"] = invitation_service.list_invitations(db, ledger_id=ledger_id)
        ctx["error"] = exc.message
        ctx["new_invitation_token"] = None
        return templates.TemplateResponse(
            request=request, name="ledger_members.html", context=ctx
        )
    return RedirectResponse(url=f"/owner/ledgers/{ledger_id}/members", status_code=303)


def _ledger_name(db: Session, ledger_id: str) -> str | None:
    from sqlalchemy import select

    from app.models import Ledger

    row = db.scalar(
        select(Ledger).where(Ledger.ledger_id == ledger_id).limit(1)
    )
    if row is None or row.archived_at is not None:
        return None
    return row.name
