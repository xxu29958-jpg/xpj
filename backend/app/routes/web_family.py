"""Family-ledger product surface for the Web client."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._web_session_common import resolve_web_actor_account_id
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _selected_option,
    _sidebar_counts,
    _web_redirect,
    templates,
)
from app.services import invitation_service
from app.tenants import AuthContext

router = APIRouter(prefix="/web/family", tags=["web-app"])


def _family_actor(
    request: Request,
    db: Session,
    *,
    ledger_id: str | None,
    require_owner: bool,
) -> tuple[list, str, int, AuthContext | None]:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    if require_owner:
        _require_selected_ledger_write(options, selected_id)
        if _selected_option(options, selected_id).role != "owner":
            raise AppError(
                "permission_denied",
                "只有账本拥有者可以管理成员和邀请。",
                status_code=403,
            )
    actor_id = resolve_web_actor_account_id(db, request, selected_id)
    return options, selected_id, actor_id, getattr(request.state, "web_session_auth", None)


def _render_family(
    request: Request,
    db: Session,
    *,
    ledger_id: str | None,
    error: str = "",
    invitation_token: str = "",
    submitted_role: str = "member",
    submitted_note: str = "",
    submitted_ttl_days: int = 7,
    status_code: int = 200,
) -> HTMLResponse:
    options, selected_id, actor_id, _auth = _family_actor(
        request,
        db,
        ledger_id=ledger_id,
        require_owner=False,
    )
    selected = _selected_option(options, selected_id)
    can_manage = selected.role == "owner"
    ctx = _base_ctx(
        request,
        db=db,
        options=options,
        selected_ledger_id=selected_id,
        page_title="家庭",
        sidebar_counts=_sidebar_counts(db, selected_id),
    )
    ctx.update(
        members=invitation_service.list_members(
            db,
            ledger_id=selected_id,
            requester_account_id=actor_id,
        ),
        invitations=(
            invitation_service.list_invitations(db, ledger_id=selected_id)
            if can_manage
            else []
        ),
        audit_logs=(
            invitation_service.list_audit_logs(db, ledger_id=selected_id, limit=50)
            if can_manage
            else []
        ),
        can_manage_family=can_manage,
        error=error,
        invitation_token=invitation_token,
        submitted_role=submitted_role,
        submitted_note=submitted_note,
        submitted_ttl_days=submitted_ttl_days,
    )
    return templates.TemplateResponse(
        request=request,
        name="family.html",
        context=ctx,
        status_code=status_code,
    )


@router.get("", response_class=HTMLResponse)
def web_family(
    request: Request,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    return _render_family(request, db, ledger_id=ledger_id)


@router.post("/invitations", response_class=HTMLResponse)
def web_family_invite(
    request: Request,
    ledger_id: str | None = None,
    role: str = Form(...),
    note: str = Form(default=""),
    ttl_days: int = Form(default=7),
    csrf_token: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    _options, selected_id, actor_id, auth = _family_actor(
        request,
        db,
        ledger_id=ledger_id,
        require_owner=True,
    )
    try:
        created = invitation_service.create_invitation(
            db,
            ledger_id=selected_id,
            role=role,
            created_by_account_id=actor_id,
            note=note,
            ttl_days=ttl_days,
            auth=auth,
        )
    except AppError as exc:
        return _render_family(
            request,
            db,
            ledger_id=selected_id,
            error=exc.message,
            submitted_role=role,
            submitted_note=note,
            submitted_ttl_days=ttl_days,
            status_code=exc.status_code,
        )
    return _render_family(
        request,
        db,
        ledger_id=selected_id,
        invitation_token=created.invite_token,
    )


def _owner_command(
    request: Request,
    db: Session,
    *,
    ledger_id: str | None,
) -> tuple[str, int, AuthContext | None]:
    _options, selected_id, actor_id, auth = _family_actor(
        request,
        db,
        ledger_id=ledger_id,
        require_owner=True,
    )
    return selected_id, actor_id, auth


def _family_command_response(
    request: Request,
    db: Session,
    *,
    selected_id: str,
    command: Callable[[], object],
) -> Response:
    try:
        command()
    except AppError as exc:
        return _render_family(
            request,
            db,
            ledger_id=selected_id,
            error=exc.message,
            status_code=exc.status_code,
        )
    return _web_redirect("/web/family", selected_id)


@router.post("/invitations/{public_id}/revoke")
def web_family_invite_revoke(
    request: Request,
    public_id: str,
    ledger_id: str | None = None,
    csrf_token: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    selected_id, actor_id, auth = _owner_command(
        request, db, ledger_id=ledger_id
    )
    return _family_command_response(
        request,
        db,
        selected_id=selected_id,
        command=lambda: invitation_service.revoke_invitation(
            db,
            ledger_id=selected_id,
            public_id=public_id,
            actor_account_id=actor_id,
            auth=auth,
        ),
    )


@router.post("/members/{member_id}/role")
def web_family_member_role(
    request: Request,
    member_id: int,
    ledger_id: str | None = None,
    role: str = Form(...),
    csrf_token: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    selected_id, actor_id, auth = _owner_command(
        request, db, ledger_id=ledger_id
    )
    return _family_command_response(
        request,
        db,
        selected_id=selected_id,
        command=lambda: invitation_service.update_member_role(
            db,
            ledger_id=selected_id,
            member_id=member_id,
            requester_account_id=actor_id,
            role=role,
            auth=auth,
        ),
    )


@router.post("/members/{member_id}/disable")
def web_family_member_disable(
    request: Request,
    member_id: int,
    ledger_id: str | None = None,
    csrf_token: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    selected_id, actor_id, auth = _owner_command(
        request, db, ledger_id=ledger_id
    )
    return _family_command_response(
        request,
        db,
        selected_id=selected_id,
        command=lambda: invitation_service.disable_member(
            db,
            ledger_id=selected_id,
            member_id=member_id,
            requester_account_id=actor_id,
            auth=auth,
        ),
    )


@router.post("/members/{member_id}/transfer-owner")
def web_family_transfer_owner(
    request: Request,
    member_id: int,
    ledger_id: str | None = None,
    confirmed: str = Form(default=""),
    csrf_token: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    selected_id, actor_id, auth = _owner_command(
        request, db, ledger_id=ledger_id
    )

    def transfer() -> object:
        if confirmed != "yes":
            raise AppError("invalid_request", "请先确认拥有者转让。", status_code=422)
        return invitation_service.transfer_ledger_owner(
            db,
            ledger_id=selected_id,
            member_id=member_id,
            requester_account_id=actor_id,
            auth=auth,
        )

    return _family_command_response(
        request,
        db,
        selected_id=selected_id,
        command=transfer,
    )
