"""/web/auth/* — public-host browser login + logout.

Reuses the existing pairing-code flow (``pair_device(platform='web')``) so
there's no new account / password system. The session token returned by
``pair_device`` is stashed in an ``__Host-session`` HttpOnly Secure cookie
and never exposed in HTML or JS.

Mounted regardless of host, but the loopback Owner Console flow doesn't
need it (LocalOnly bypasses session). The public Host flow (PR-4 will
wire ``LocalOrWebSession`` dependency into every /web route) will fall
back here when there's no valid cookie.

Schema: zero changes. ``AuthToken.scope='app'`` with ``Device.platform='web'``
already distinguishes browser sessions from Android sessions; revoke /
logout / sessions list all run through the same code paths.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.models import AuthToken
from app.routes.web_common import templates
from app.services.identity_service import (
    authenticate_session_token,
    hash_secret,
    pair_device,
)
from app.services.time_service import now_utc

router = APIRouter(prefix="/web/auth", tags=["web"])

SESSION_COOKIE_NAME = "__Host-session"
SESSION_COOKIE_MAX_AGE_SECONDS = 8 * 60 * 60  # 8h sliding window (extended on activity)
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
        samesite="lax",
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
        samesite="lax",
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
    remote_id = request.client.host if request.client else None
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
        # Revoke the underlying AuthToken so the cookie value, if ever
        # leaked or replayed, is also dead server-side.
        row = db.scalar(
            select(AuthToken).where(AuthToken.token_hash == hash_secret(token)).limit(1)
        )
        if row is not None and row.revoked_at is None:
            row.revoked_at = now_utc()
            db.commit()
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
    auth = authenticate_session_token(db, token, {"app"})
    return Response(
        content=(
            '{"account_name":"' + _escape(auth.account_name) + '",'
            '"ledger_id":"' + _escape(auth.ledger_id) + '",'
            '"role":"' + _escape(auth.role) + '"}'
        ),
        media_type="application/json; charset=utf-8",
    )


# ── helpers ─────────────────────────────────────────────────────────────────


_ERROR_MESSAGES = {
    "invalid_pairing_code": "绑定码不正确，请重新输入 8 位数字。",
    "pairing_code_used": "绑定码已被使用，请向账本所有者索取新的绑定码。",
    "pairing_code_expired": "绑定码已过期，请向账本所有者索取新的绑定码。",
    "invalid_token": "登录已失效，请重新输入绑定码。",
    "rate_limited": "请求过于频繁，请稍后再试。",
}


def _redirect_login(*, next: str, error: str) -> RedirectResponse:  # noqa: A002
    target = "/web/auth/login"
    params = []
    safe_next = _safe_next_url(next)
    if safe_next:
        params.append(f"next={safe_next}")
    if error:
        params.append(f"error={error}")
    if params:
        target = f"{target}?{'&'.join(params)}"
    return RedirectResponse(url=target, status_code=303)


def _safe_next_url(raw: str | None) -> str:
    """Only allow same-site /web/... redirects after login. Reject anything
    that could redirect off-site (open-redirect class vulnerability)."""
    if not raw:
        return ""
    candidate = raw.strip()
    if not candidate.startswith("/web") or candidate.startswith("//") or candidate.startswith("/web//"):
        return ""
    # Disallow embedded scheme / line break
    for bad in (":", "\n", "\r"):
        if bad in candidate:
            return ""
    return candidate


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
