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

import secrets
from urllib.parse import urlencode
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.network_boundary import pairing_rate_limit_key
from app.routes.web_common import _read_ui_theme, _safe_same_site_redirect_path, templates
from app.services.identity_service import (
    ENROLLMENT_PROOF_COOKIE_SECONDS,
    authenticate_web_session_token,
    pair_device,
)
from app.services.session_lifecycle_service import WEB_SESSION_TTL_SECONDS, revoke_web_session_token
from app.version import BACKEND_VERSION, STATIC_ASSET_VERSION

router = APIRouter(prefix="/web/auth", tags=["web"])

SESSION_COOKIE_NAME = "__Host-session"
SESSION_COOKIE_MAX_AGE_SECONDS = WEB_SESSION_TTL_SECONDS  # fixed 8h server-side TTL
PAIRING_ATTEMPT_COOKIE_NAME = "__Secure-pairing-attempt"
PAIRING_ATTEMPT_COOKIE_PATH = "/web/auth"
PAIRING_ATTEMPT_COOKIE_MAX_AGE_SECONDS = ENROLLMENT_PROOF_COOKIE_SECONDS
# `__Host-` prefix demands: Secure, Path=/, no Domain attribute. Browsers
# refuse to honour the cookie if any of these is missing or modified.
# See the MDN cookie-prefix reference for the browser-side invariants.


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


def _set_pairing_attempt_cookie(response: Response, value: str) -> None:
    response.set_cookie(
        key=PAIRING_ATTEMPT_COOKIE_NAME,
        value=value,
        max_age=PAIRING_ATTEMPT_COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        secure=True,
        samesite="strict",
        path=PAIRING_ATTEMPT_COOKIE_PATH,
    )


def _clear_pairing_attempt_cookie(response: Response) -> None:
    response.delete_cookie(
        key=PAIRING_ATTEMPT_COOKIE_NAME,
        path=PAIRING_ATTEMPT_COOKIE_PATH,
        secure=True,
        httponly=True,
        samesite="strict",
    )


def _new_pairing_attempt_cookie() -> str:
    return f"{uuid4()}.{secrets.token_urlsafe(32)}"


def _read_pairing_attempt(request: Request) -> tuple[str, str] | None:
    raw = request.cookies.get(PAIRING_ATTEMPT_COOKIE_NAME, "").strip()
    attempt_id, separator, attempt_secret = raw.partition(".")
    if separator != "." or len(attempt_secret) != 43:
        return None
    if not all(char.isascii() and (char.isalnum() or char in "_-") for char in attempt_secret):
        return None
    try:
        canonical_id = str(UUID(attempt_id))
    except ValueError:
        return None
    if canonical_id != attempt_id:
        return None
    return canonical_id, attempt_secret


def read_session_token(request: Request) -> str | None:
    raw = request.cookies.get(SESSION_COOKIE_NAME, "").strip()
    return raw or None


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
def web_login_form(
    request: Request,
    next: str | None = None,  # noqa: A002 - matches `?next=` convention
    error: str | None = None,
) -> HTMLResponse:
    error_message = ""
    if error:
        error_message = _ERROR_MESSAGES.get(error, _GENERIC_ERROR_MESSAGE)
    response = templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context={
            "next_url": _safe_next_url(next),
            "error_message": error_message,
            "backend_version": BACKEND_VERSION,
            "asset_version": STATIC_ASSET_VERSION,
            "ui_theme": _read_ui_theme(request),
        },
    )
    if _read_pairing_attempt(request) is None:
        _set_pairing_attempt_cookie(response, _new_pairing_attempt_cookie())
    return response


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
    attempt = _read_pairing_attempt(request)
    if attempt is None:
        redirect = _redirect_login(next=next, error="pairing_attempt_expired")
        _clear_pairing_attempt_cookie(redirect)
        return redirect
    cleaned_device_name = _clean_device_name(device_name)
    remote_id = pairing_rate_limit_key(request)
    try:
        result = pair_device(
            db,
            pairing_code=code,
            pairing_attempt_id=attempt[0],
            pairing_attempt_secret=attempt[1],
            device_name=cleaned_device_name,
            platform="web",
            remote_id=remote_id,
        )
    except AppError as exc:
        redirect = _redirect_login(next=next, error=exc.error)
        if exc.error in {"pairing_attempt_expired", "pairing_attempt_closed"}:
            _clear_pairing_attempt_cookie(redirect)
        return redirect
    redirect = RedirectResponse(url=_safe_next_url(next) or "/web", status_code=303)
    set_session_cookie(redirect, result.session_token)
    _clear_pairing_attempt_cookie(redirect)
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
    "invalid_pairing_code": "连接码不正确，请重新输入 8 位数字。",
    "invalid_token": "连接已失效，请重新输入连接码。",
    "pairing_attempt_expired": "连接页面已过期，请刷新后重新输入连接码。",
    "pairing_attempt_closed": "这次连接已经结束，请重新获取连接码。",
    "rate_limited": "请求过于频繁，请稍后再试。",
}
_GENERIC_ERROR_MESSAGE = "暂时无法连接，请重新获取连接码后再试。"


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


def _clean_device_name(raw: str) -> str:
    cleaned = (raw or "").strip()
    if cleaned:
        return cleaned[:120]
    return "浏览器"


def _escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
    )
