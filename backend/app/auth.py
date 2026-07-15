from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.services.identity_service import (
    authenticate_session_principal,
    authenticate_session_token,
    is_legacy_app_token,
)
from app.tenants import AuthContext, SessionPrincipal


@dataclass(frozen=True)
class AuthenticatedAppSession:
    token: str
    principal: SessionPrincipal


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise AppError("invalid_token", status_code=401)
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise AppError("invalid_token", status_code=401)
    return token


def _raise_legacy_app_removed() -> None:
    raise AppError("legacy_auth_removed", "请使用新版绑定方式。", status_code=401)


def get_current_app_context(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
    x_ticketbox_ledger_id: str | None = Header(
        default=None,
        alias="X-Ticketbox-Ledger-ID",
    ),
) -> AuthContext:
    token = _bearer_token(authorization)
    if is_legacy_app_token(token):
        _raise_legacy_app_removed()
    return authenticate_session_token(
        db,
        token,
        {"app"},
        selected_ledger_id=(x_ticketbox_ledger_id or "").strip() or None,
    )


def get_optional_current_app_session(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> AuthenticatedAppSession | None:
    """Authenticate an optional bearer without downgrading malformed auth.

    Public enrollment endpoints may be called by an unbound installation, but
    once a bearer is present it must prove the exact existing Account/Device.
    """

    if authorization is None:
        return None
    token = _bearer_token(authorization)
    if is_legacy_app_token(token):
        _raise_legacy_app_removed()
    principal = authenticate_session_principal(db, token, {"app"})
    return AuthenticatedAppSession(token=token, principal=principal)


def get_current_app_principal(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> SessionPrincipal:
    token = _bearer_token(authorization)
    if is_legacy_app_token(token):
        _raise_legacy_app_removed()
    return authenticate_session_principal(db, token, {"app"})


def get_current_admin_context(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> AuthContext:
    from app.services import permission_service

    token = _bearer_token(authorization)
    if is_legacy_app_token(token):
        _raise_legacy_app_removed()
    auth = authenticate_session_token(db, token, {"app", "admin"})
    permission_service.require_admin_maintenance(auth)
    return auth


def get_current_owner_or_admin_context(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
    x_ticketbox_ledger_id: str | None = Header(
        default=None,
        alias="X-Ticketbox-Ledger-ID",
    ),
) -> AuthContext:
    from app.services import permission_service

    token = _bearer_token(authorization)
    if is_legacy_app_token(token):
        _raise_legacy_app_removed()
    auth = authenticate_session_token(
        db,
        token,
        {"app", "admin"},
        selected_ledger_id=(x_ticketbox_ledger_id or "").strip() or None,
    )
    permission_service.require_create_top_level_ledger(auth)
    return auth


def get_current_ledger_app_context(
    ledger_id: str,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> AuthContext:
    """App token for the ledger named in the route path.

    Use this for ``/api/ledgers/{ledger_id}/...`` routes so the path ledger
    check is a reusable auth guard instead of repeated route-body logic.
    """
    token = _bearer_token(authorization)
    if is_legacy_app_token(token):
        _raise_legacy_app_removed()
    return authenticate_session_token(
        db,
        token,
        {"app"},
        selected_ledger_id=ledger_id,
        selected_ledger_error="ledger_not_found",
    )


def get_current_member_manager_context(
    auth: AuthContext = Depends(get_current_ledger_app_context),
) -> AuthContext:
    """App token for the path ledger with member-management permission."""
    from app.services import permission_service

    permission_service.require_manage_members(auth)
    return auth


def get_current_writer_context(
    auth: AuthContext = Depends(get_current_app_context),
) -> AuthContext:
    """v0.4-beta1: app token with write permission (owner/member). Viewer 403."""
    from app.services import permission_service

    permission_service.require_write_expense(auth)
    return auth


def get_current_owner_app_context(
    auth: AuthContext = Depends(get_current_app_context),
) -> AuthContext:
    """v0.4-beta1: app token owned by the ledger's owner role.

    Unlike ``get_current_owner_or_admin_context`` this rejects admin-scoped
    tokens — used for endpoints (e.g. invitation create) that must be
    initiated by the actual owner account through their app session.
    """
    from app.services import permission_service

    permission_service.require_manage_members(auth)
    return auth


def verify_app_token(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> AuthContext:
    return get_current_app_context(authorization, db)


def verify_admin_token(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> AuthContext:
    return get_current_admin_context(authorization, db)
