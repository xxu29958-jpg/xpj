"""Loopback-only Desktop bridge session lifecycle surface (218-E).

The Desktop product shell talks to the backend over the loopback bridge
(``X-Ticketbox-Desktop-Bridge: v1`` + a paired ``platform=desktop`` app
bearer). These routes are excluded from the public OpenAPI schema: the
bridge marker is a non-simple header, so a browser cross-origin call must
preflight and can never forge the principal.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request, Response, status
from sqlalchemy.orm import Session

from app.auth import _bearer_token
from app.database import get_db
from app.errors import AppError
from app.middleware.web_session import DESKTOP_BRIDGE_HEADER, DESKTOP_BRIDGE_VERSION
from app.network_boundary import require_owner_console_local
from app.services.desktop_switch_service import revoke_desktop_app_session
from app.services.identity_service import authenticate_desktop_session_token
from app.tenants import AuthContext

router = APIRouter(
    prefix="/desktop",
    tags=["desktop"],
    include_in_schema=False,
)


def _require_desktop_bridge(request: Request) -> None:
    """Require loopback plus a non-simple header so browser CSRF must preflight."""
    require_owner_console_local(request)
    if request.headers.get(DESKTOP_BRIDGE_HEADER) != DESKTOP_BRIDGE_VERSION:
        raise AppError("desktop_bridge_required", status_code=401)


def _get_current_desktop_context(
    request: Request,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> AuthContext:
    """Resolve only a live app credential bound to a Desktop device."""
    auth = authenticate_desktop_session_token(
        db,
        _bearer_token(authorization),
    )
    _require_desktop_bridge(request)
    return auth


@router.post("/session/revoke", status_code=status.HTTP_204_NO_CONTENT)
def revoke_desktop_session(
    authorization: str | None = Header(default=None),
    scope: str | None = None,
    auth: AuthContext = Depends(_get_current_desktop_context),
    db: Session = Depends(get_db),
) -> Response:
    """Revoke the presented credential (default) or its whole lineage.

    Default: the presented row plus still-staged pending rows — the
    ledger-switch cleanup intent, which keeps the promoted successor alive.
    ``?scope=lineage`` (unpair/teardown intent): additionally kills every
    promoted replacement whose receipt names this credential as predecessor.
    Unrelated lineages, other devices' sessions, and the device itself stay
    untouched.
    """
    if scope not in (None, "lineage"):
        raise AppError("invalid_request", status_code=400)
    revoke_desktop_app_session(
        db,
        auth=auth,
        token_value=_bearer_token(authorization),
        lineage=scope == "lineage",
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
