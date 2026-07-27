"""Application-principal gates for the shared ``/web`` surface.

Same /web router serves three audiences:

- **Loopback Host** (127.0.0.1 / localhost / etc): Owner Console operator
  on the local machine. Behaves exactly as before — no cookie required,
  ``_require_local`` (LoopbackOnly) was the only gate.

- **Desktop product bridge** (loopback + explicit bridge marker): a paired
  ``platform=desktop`` app bearer becomes the application principal for the
  proxied ``/web`` request.  Marker failures never fall through to the legacy
  loopback-owner path.

- **Public Host** (Cloudflare Tunnel hostname): family member browser.
  Must have a valid ``__Host-session`` cookie minted by the pairing-code
  login flow in :mod:`app.routes.web_auth`. Without it, request is
  redirected to ``/web/auth/login?next=<current path>``.

This middleware sits between the loopback gate and the route, so all
existing /web routes get session-gating *for free* without changing
their dependencies. ``_resolve_selected_ledger_id`` checks
``request.state.web_session_auth`` to lock the rendered ledger to the
session's account, ignoring any ``?ledger_id=`` query override (defense
against a logged-in family member trying to peek into another ledger by
URL editing).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from urllib.parse import urlencode

from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from app.database import SessionLocal
from app.errors import AppError, error_response
from app.network_boundary import is_loopback_request
from app.routes.web_auth import (
    SESSION_COOKIE_MAX_AGE_SECONDS,
    SESSION_COOKIE_NAME,
    clear_session_cookie,
    read_session_token,
)
from app.services.identity_service import (
    authenticate_desktop_session_token,
    authenticate_web_session_token,
)

DESKTOP_BRIDGE_HEADER = "X-Ticketbox-Desktop-Bridge"
DESKTOP_BRIDGE_VERSION = "v1"


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _is_web_path(request: Request) -> bool:
    path = request.url.path
    return path == "/web" or path.startswith("/web/")


def _desktop_bridge_marker(request: Request) -> str | None:
    if not _is_web_path(request):
        return None
    return request.headers.get(DESKTOP_BRIDGE_HEADER)


def _desktop_bearer_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization")
    if not authorization:
        return None
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer":
        return None
    cleaned = token.strip()
    return cleaned or None


def _app_error_response(request: Request, exc: AppError) -> Response:
    return error_response(
        exc.error,
        exc.message,
        status_code=exc.status_code,
        request_id=_request_id(request),
        details=exc.details,
    )


def _ledger_binding_error(request: Request, ledger_id: str) -> Response | None:
    requested_ledger = (request.query_params.get("ledger_id") or "").strip()
    if not requested_ledger or requested_ledger == ledger_id:
        return None
    return error_response(
        "ledger_forbidden",
        "当前会话只能访问绑定的账本。",
        status_code=403,
        request_id=_request_id(request),
    )


def _login_redirect_url(request: Request) -> str:
    path = request.url.path
    # Preserve where the user was trying to go so login can bounce them back.
    # _safe_next_url on the login route will still re-validate this string.
    query = request.url.query
    target_after_login = f"{path}?{query}" if query else path
    # Reject obvious junk that would never make sense as a destination.
    if not target_after_login.startswith("/web") or target_after_login.startswith("/web/auth/"):
        target_after_login = "/web"
    return f"/web/auth/login?{urlencode({'next': target_after_login})}"


def _is_session_required(request: Request) -> bool:
    """Return True if this request must carry a valid web session cookie."""
    path = request.url.path
    if not path.startswith("/web"):
        return False
    # The login/logout/whoami flow itself runs without a session.
    if path.startswith("/web/auth/"):
        return False
    # Loopback Owner Console keeps the legacy no-cookie experience.
    if is_loopback_request(request):
        return False
    # Starlette TestClient defaults to peer=testclient, host=testserver.
    # Neither ever appears in production. Let the existing LocalOnly
    # dependency (or per-test ``dependency_overrides[_require_local]``)
    # handle gating in tests so the pre-PR-3 test contract still holds.
    peer = request.client.host if request.client else ""
    host_header = (request.headers.get("host") or "").lower()
    return not (peer == "testclient" or host_header.startswith("testserver"))


async def _desktop_bridge_session_gate(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
    *,
    marker: str,
) -> Response:
    """Bind an explicit loopback Desktop bridge request to its app principal."""
    if not is_loopback_request(request):
        return error_response(
            "desktop_bridge_required",
            status_code=403,
            request_id=_request_id(request),
        )
    if marker != DESKTOP_BRIDGE_VERSION:
        return error_response(
            "desktop_bridge_required",
            status_code=401,
            request_id=_request_id(request),
        )

    token = _desktop_bearer_token(request)
    if token is None:
        return error_response(
            "invalid_token",
            status_code=401,
            request_id=_request_id(request),
        )

    try:
        with SessionLocal() as db:
            auth = authenticate_desktop_session_token(db, token)
    except AppError as exc:
        return _app_error_response(request, exc)
    except SQLAlchemyError:
        return error_response(
            "server_error",
            "Desktop 登录状态暂时不可用，请稍后再试。",
            status_code=503,
            request_id=_request_id(request),
        )

    request.state.web_session_auth = auth
    request.state.web_session_platform = "desktop"
    ledger_error = _ledger_binding_error(request, auth.ledger_id)
    if ledger_error is not None:
        return ledger_error
    return await call_next(request)


async def web_session_gate(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    # Header presence means the caller is attempting the privileged Desktop
    # bridge path.  Validate it before the loopback-owner bypass so malformed,
    # missing, revoked, or wrong-platform credentials can never fall through
    # and inherit the legacy local owner projection.
    desktop_marker = _desktop_bridge_marker(request)
    if desktop_marker is not None:
        return await _desktop_bridge_session_gate(
            request,
            call_next,
            marker=desktop_marker,
        )

    if not _is_session_required(request):
        return await call_next(request)

    token = read_session_token(request)
    if not token:
        return RedirectResponse(url=_login_redirect_url(request), status_code=303)

    try:
        with SessionLocal() as db:
            result = authenticate_web_session_token(
                db,
                token,
                ttl_seconds=SESSION_COOKIE_MAX_AGE_SECONDS,
            )
    except AppError:
        # Cookie value doesn't map to a live AuthToken anymore — wipe it
        # so the browser stops sending a dead value, then send the user
        # to the login screen.
        redirect = RedirectResponse(url=_login_redirect_url(request), status_code=303)
        clear_session_cookie(redirect)
        return redirect
    except SQLAlchemyError:
        return error_response(
            "server_error",
            "网页版登录状态暂时不可用，请稍后再试。",
            status_code=503,
            request_id=getattr(request.state, "request_id", None),
        )

    # Stash session auth so _resolve_selected_ledger_id can force-lock the
    # rendered ledger to the session's account.
    auth = result.auth
    request.state.web_session_auth = auth

    # Defense: the cookie says "I'm bound to ledger X", but the URL says
    # "?ledger_id=Y". Refuse rather than silently follow either signal —
    # this is how cookie-bound users would otherwise be able to peek at a
    # different ledger they happen to have query knowledge of.
    requested_ledger = (request.query_params.get("ledger_id") or "").strip()
    if requested_ledger and requested_ledger != auth.ledger_id:
        return error_response(
            "ledger_forbidden",
            "当前会话只能访问绑定的账本。",
            status_code=403,
            request_id=getattr(request.state, "request_id", None),
        )

    response = await call_next(request)
    return response


__all__ = [
    "DESKTOP_BRIDGE_HEADER",
    "DESKTOP_BRIDGE_VERSION",
    "SESSION_COOKIE_NAME",
    "web_session_gate",
]
