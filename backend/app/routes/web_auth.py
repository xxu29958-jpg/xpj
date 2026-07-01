"""/web/auth/* — public-host browser login + logout.

Reuses the existing pairing-code flow (``pair_device(platform='web')``) so
there's no new account / password system. The session token returned by
``pair_device`` is stashed in an ``__Host-session`` HttpOnly Secure cookie
and never exposed in HTML or JS.

Mounted regardless of host, but the loopback Owner Console flow doesn't
need it (LocalOnly bypasses session). The public Host flow (PR-4 will
wire ``LocalOrWebSession`` dependency into every /web route) will fall
back here when there's no valid cookie.

Session boundary: browser cookies are backed by ``AuthToken.scope='app'`` with
``Device.platform='web'`` plus a fixed ``AuthToken.expires_at`` server TTL.
Android app tokens must never be accepted from ``__Host-session`` cookies.
"""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.network_boundary import pairing_rate_limit_key
from app.routes.web_common import _safe_same_site_redirect_path, templates
from app.services.identity_service import (
    WEB_SESSION_TTL_SECONDS,
    authenticate_web_session_token,
    pair_device,
)
from app.services.session_lifecycle_service import revoke_web_session_token
from app.version import BACKEND_VERSION, STATIC_ASSET_VERSION

router = APIRouter(prefix="/web/auth", tags=["web"])

SESSION_COOKIE_NAME = "__Host-session"
SESSION_COOKIE_MAX_AGE_SECONDS = WEB_SESSION_TTL_SECONDS  # fixed 8h server-side TTL
# `__Host-` prefix demands: Secure, Path=/, no Domain attribute. Browsers
# refuse to honour the cookie if any of these is missing or modified.
# See https://developer.mozilla.org/en-US/docs/Web/HTTP/Cookies#cookie_prefixes


def set_session_cookie(response: Response, session_token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        max_age=SESSION_COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    # Browsers require matching attributes to honour the delete. The
    # __Host- prefix means: same Secure + Path=/, no Domain.
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )


def read_session_token(request: Request) -> str | None:
    raw = request.cookies.get(SESSION_COOKIE_NAME, "").strip()
    return raw or None


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
def web_login_form(
    request: Request,
    next: str | None = None,  # noqa: A002 - matches `?next=` convention
    error: str | None = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context={
            "next_url": _safe_next_url(next),
            "error_message": _ERROR_MESSAGES.get(error or "", "") if error else "",
            "backend_version": BACKEND_VERSION,
            "asset_version": STATIC_ASSET_VERSION,
        },
    )


@router.post("/login", response_class=HTMLResponse, include_in_schema=False)
def web_login_submit(
    request: Request,
    pairing_code: str = Form(default=""),
    device_name: str = Form(default=""),
    next: str = Form(default=""),  # noqa: A002 - matches `?next=` convention
    db: Session = Depends(get_db),
) -> Response:
    code = (pairing_code or "").strip()
    if not code or not code.isdigit() or len(code) != 8:
        return _redirect_login(next=next, error="invalid_pairing_code")
    cleaned_device_name = _clean_device_name(device_name, request)
    remote_id = pairing_rate_limit_key(request)
    try:
        result = pair_device(
            db,
            pairing_code=code,
            device_name=cleaned_device_name,
            platform="web",
            remote_id=remote_id,
        )
    except AppError as exc:
        return _redirect_login(next=next, error=exc.error)
    redirect = RedirectResponse(url=_safe_next_url(next) or "/web", status_code=303)
    set_session_cookie(redirect, result.session_token)
    return redirect


@router.post("/logout", response_class=HTMLResponse, include_in_schema=False)
def web_logout(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    token = read_session_token(request)
    redirect = RedirectResponse(url="/web/auth/login", status_code=303)
    if token:
        # Revoke the backing AuthToken (only if it actually maps to a
        # platform="web" scope="app" row) so the cookie value, if ever
        # leaked or replayed, is dead server-side.
        revoke_web_session_token(db, token_value=token)
    clear_session_cookie(redirect)
    return redirect


@router.get("/whoami", include_in_schema=False)
def web_whoami(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """Diagnostic endpoint: returns 200 + masked account info when the
    current cookie maps to an active AuthToken, 401 otherwise. Useful for
    the public Host /web smoke test before flipping LocalOnly off in PR-4."""

    token = read_session_token(request)
    if not token:
        raise AppError("invalid_token", status_code=401)
    result = authenticate_web_session_token(
        db,
        token,
        ttl_seconds=SESSION_COOKIE_MAX_AGE_SECONDS,
    )
    auth = result.auth
    response = Response(
        content=(
            '{"account_name":"' + _escape(auth.account_name) + '",'
            '"ledger_id":"' + _escape(auth.ledger_id) + '",'
            '"role":"' + _escape(auth.role) + '"}'
        ),
        media_type="application/json; charset=utf-8",
    )
    return response


# ── helpers ─────────────────────────────────────────────────────────────────


_ERROR_MESSAGES = {
    "invalid_pairing_code": "绑定码不正确，请重新输入 8 位数字。",
    "invalid_token": "登录已失效，请重新输入绑定码。",
    "rate_limited": "请求过于频繁，请稍后再试。",
}


def _redirect_login(*, next: str, error: str) -> RedirectResponse:  # noqa: A002
    target = "/web/auth/login"
    params: dict[str, str] = {}
    safe_next = _safe_next_url(next)
    if safe_next:
        params["next"] = safe_next
    if error:
        params["error"] = error
    if params:
        target = f"{target}?{urlencode(params)}"
    return RedirectResponse(url=target, status_code=303)


def _safe_next_url(raw: str | None) -> str:
    """Only allow same-site /web/... redirects after login. Reject anything
    that could redirect off-site (open-redirect class vulnerability)."""
    return _safe_same_site_redirect_path(raw, allowed_roots=("/web",), fallback="")


def _clean_device_name(raw: str, request: Request) -> str:
    cleaned = (raw or "").strip()
    if cleaned:
        return cleaned[:120]
    ua = (request.headers.get("user-agent") or "").strip()
    if ua:
        return ("浏览器 / " + ua[:100]).strip()
    return "Web Browser"


def _escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
    )
