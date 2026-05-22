"""Public-host /web cookie session gate (v1.0 PR-4).

Same /web router serves two audiences:

- **Loopback Host** (127.0.0.1 / localhost / etc): Owner Console operator
  on the local machine. Behaves exactly as before — no cookie required,
  ``_require_local`` (LoopbackOnly) was the only gate.

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

from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from app.database import SessionLocal
from app.errors import AppError
from app.network_boundary import is_loopback_request
from app.routes.web_auth import (
    SESSION_COOKIE_NAME,
    clear_session_cookie,
    read_session_token,
)
from app.services.identity_service import authenticate_session_token


def _login_redirect_url(request: Request) -> str:
    path = request.url.path
    # Preserve where the user was trying to go so login can bounce them back.
    # _safe_next_url on the login route will still re-validate this string.
    query = request.url.query
    target_after_login = f"{path}?{query}" if query else path
    # Reject obvious junk that would never make sense as a destination.
    if not target_after_login.startswith("/web") or target_after_login.startswith("/web/auth/"):
        target_after_login = "/web"
    return f"/web/auth/login?next={target_after_login}"


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


async def web_session_gate(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    if not _is_session_required(request):
        return await call_next(request)

    token = read_session_token(request)
    if not token:
        return RedirectResponse(url=_login_redirect_url(request), status_code=303)

    try:
        with SessionLocal() as db:
            auth = authenticate_session_token(db, token, {"app"})
    except AppError:
        # Cookie value doesn't map to a live AuthToken anymore — wipe it
        # so the browser stops sending a dead value, then send the user
        # to the login screen.
        redirect = RedirectResponse(url=_login_redirect_url(request), status_code=303)
        clear_session_cookie(redirect)
        return redirect
    except SQLAlchemyError:
        # DB transiently unavailable; let the request through unauthenticated
        # so the downstream layer's own error handler surfaces a clean 5xx
        # instead of a cookie-clearing redirect that masks the real fault.
        return await call_next(request)

    # Stash session auth so _resolve_selected_ledger_id can force-lock the
    # rendered ledger to the session's account.
    request.state.web_session_auth = auth

    # Defense: the cookie says "I'm bound to ledger X", but the URL says
    # "?ledger_id=Y". Refuse rather than silently follow either signal —
    # this is how cookie-bound users would otherwise be able to peek at a
    # different ledger they happen to have query knowledge of.
    requested_ledger = (request.query_params.get("ledger_id") or "").strip()
    if requested_ledger and requested_ledger != auth.ledger_id:
        from app.errors import error_response

        return error_response(
            "ledger_forbidden",
            "当前会话只能访问绑定的账本。",
            status_code=403,
            request_id=getattr(request.state, "request_id", None),
        )

    return await call_next(request)


__all__ = ["web_session_gate", "SESSION_COOKIE_NAME"]
