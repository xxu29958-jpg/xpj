"""Loopback-only data plane for the native Desktop product window."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Path, Request, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.network_boundary import require_owner_console_local
from app.schemas._desktop_product import (
    DesktopInboxCommandRequest,
    DesktopInboxCommandResponse,
    DesktopProductLedger,
    DesktopWorkspaceKey,
    DesktopWorkspaceResponse,
)
from app.services.desktop_product_command_service import (
    execute_desktop_inbox_command,
)
from app.services.desktop_product_identity_service import revoke_desktop_app_session
from app.services.desktop_product_service import build_desktop_workspace
from app.services.identity_service import authenticate_desktop_session_token
from app.services.permission_service import require_write_expense
from app.tenants import AuthContext

router = APIRouter(
    prefix="/desktop",
    tags=["desktop"],
    include_in_schema=False,
)


def _require_desktop_bridge(request: Request) -> None:
    """Require loopback plus a non-simple header so browser CSRF must preflight."""
    require_owner_console_local(request)
    if request.headers.get("X-Ticketbox-Desktop-Bridge") != "v1":
        raise AppError(
            "desktop_bridge_required",
            "Desktop 数据面只接受本机产品桥请求。",
            status_code=401,
        )


def _bearer_token_value(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise AppError("invalid_token", status_code=401)
    token_value = authorization.removeprefix("Bearer ").strip()
    if not token_value:
        raise AppError("invalid_token", status_code=401)
    return token_value


def _get_current_desktop_context(
    request: Request,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> AuthContext:
    """Resolve only a live app credential bound to a Desktop device."""
    auth = authenticate_desktop_session_token(
        db,
        _bearer_token_value(authorization),
    )
    _require_desktop_bridge(request)
    return auth


def _get_current_desktop_writer_context(
    auth: AuthContext = Depends(_get_current_desktop_context),
) -> AuthContext:
    require_write_expense(auth)
    return auth


@router.get("/workspaces/{workspace}", response_model=DesktopWorkspaceResponse)
def desktop_workspace(
    workspace: DesktopWorkspaceKey,
    ledger_id: str | None = None,
    auth: AuthContext = Depends(_get_current_desktop_context),
    db: Session = Depends(get_db),
) -> DesktopWorkspaceResponse:
    if ledger_id and ledger_id != auth.ledger_id:
        raise AppError("ledger_not_found", status_code=404)
    ledgers = [
        DesktopProductLedger(
            ledger_id=auth.ledger_id,
            name=auth.ledger_name,
            role=auth.role,
            is_default=True,
            is_current=True,
        )
    ]
    return build_desktop_workspace(
        db,
        workspace=workspace,
        account_id=auth.account_id,
        ledger_id=auth.ledger_id,
        ledger_name=auth.ledger_name,
        role=auth.role,
        ledgers=ledgers,
    )


@router.post(
    "/workspaces/inbox/expenses/{public_id}/commands",
    response_model=DesktopInboxCommandResponse,
)
def desktop_inbox_command(
    payload: DesktopInboxCommandRequest,
    public_id: str = Path(min_length=1, max_length=64),
    ledger_id: str | None = None,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(_get_current_desktop_writer_context),
    db: Session = Depends(get_db),
) -> DesktopInboxCommandResponse:
    if ledger_id and ledger_id != auth.ledger_id:
        raise AppError("ledger_not_found", status_code=404)
    return execute_desktop_inbox_command(
        db,
        auth=auth,
        public_id=public_id,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post("/session/revoke", status_code=status.HTTP_204_NO_CONTENT)
def revoke_desktop_session(
    authorization: str | None = Header(default=None),
    auth: AuthContext = Depends(_get_current_desktop_context),
    db: Session = Depends(get_db),
) -> Response:
    revoke_desktop_app_session(
        db,
        auth=auth,
        token_value=_bearer_token_value(authorization),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
