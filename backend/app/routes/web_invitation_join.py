"""Public browser adapter for previewing and accepting a family invitation."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import parse_qsl, urlsplit

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.errors import AppError
from app.routes.web_auth import (
    _clear_pairing_attempt_cookie,
    _new_pairing_attempt_cookie,
    _read_pairing_attempt,
    _set_pairing_attempt_cookie,
    clear_session_cookie,
    read_session_token,
    set_session_cookie,
)
from app.routes.web_common import _read_ui_theme, _with_ledger, templates
from app.services.identity_service import authenticate_web_session_principal
from app.services.installation_health_service import configured_mobile_endpoint_url
from app.services.invitation_service import (
    InvitationPreviewResult,
    accept_invitation,
    preview_invitation,
)
from app.services.session_lifecycle_service import WEB_SESSION_TTL_SECONDS
from app.services.spending_contract_service import accounting_datetime_label
from app.tenants import SessionPrincipal
from app.version import BACKEND_VERSION, STATIC_ASSET_VERSION

router = APIRouter(prefix="/web/auth/join", tags=["web"])
_INVALID_INVITATION_INPUT = "只能使用家人发来的小票夹邀请链接或邀请码。"


def _https_origin(raw: str) -> str | None:
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        return None
    host = parsed.hostname.casefold()
    authority = f"[{host}]" if ":" in host else host
    if port not in {None, 443}:
        authority = f"{authority}:{port}"
    return f"https://{authority}"


def _trusted_invitation_origins(request: Request) -> set[str]:
    configured = configured_mobile_endpoint_url(get_settings().public_base_url)
    origins = {configured} if configured else set()
    request_origin = _https_origin(str(request.base_url).rstrip("/"))
    source_origin = _https_origin(request.headers.get("origin", ""))
    if request_origin is not None and source_origin == request_origin:
        origins.add(request_origin)
    return origins


def _canonical_invite_token(request: Request, raw: str) -> str:
    value = (raw or "").strip()
    if value.startswith("inv_") and len(value) <= 128:
        return value
    if len(value) > 2048:
        raise AppError("invalid_request", _INVALID_INVITATION_INPUT, status_code=422)
    try:
        parsed = urlsplit(value)
        source_origin = _https_origin(value)
    except ValueError as exc:
        raise AppError("invalid_request", _INVALID_INVITATION_INPUT, status_code=422) from exc
    fragment = parse_qsl(parsed.fragment, keep_blank_values=True)
    if (
        source_origin not in _trusted_invitation_origins(request)
        or parsed.path != "/web/auth/join"
        or parsed.query
        or len(fragment) != 1
        or fragment[0][0] != "invite"
    ):
        raise AppError("invalid_request", _INVALID_INVITATION_INPUT, status_code=422)
    token = fragment[0][1].strip()
    if not token.startswith("inv_") or len(token) > 128:
        raise AppError("invalid_request", _INVALID_INVITATION_INPUT, status_code=422)
    return token


def _browser_identity(
    request: Request,
    db: Session,
) -> tuple[str | None, SessionPrincipal | None, bool]:
    session_token = read_session_token(request)
    if session_token is None:
        return None, None, False
    try:
        principal = authenticate_web_session_principal(
            db,
            session_token,
            ttl_seconds=WEB_SESSION_TTL_SECONDS,
        )
    except AppError as exc:
        if exc.error != "invalid_token":
            raise
        return session_token, None, True
    return session_token, principal, False


def _expires_label(value: str | None) -> str:
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return "—"
    return accounting_datetime_label(parsed) or "—"


def _render_join(
    request: Request,
    *,
    preview: InvitationPreviewResult | None = None,
    invite_token: str = "",
    account_name: str = "",
    current_account_name: str = "",
    error: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="auth/join.html",
        context={
            "preview": preview,
            "invite_token": invite_token,
            "account_name": account_name,
            "current_account_name": current_account_name,
            "expires_label": _expires_label(preview.expires_at) if preview else "",
            "permission_label": (
                {
                    "member": "成员，可以和家人一起记账",
                    "viewer": "只读，只能查看家庭账目",
                }.get(preview.role, preview.role)
                if preview
                else ""
            ),
            "error": error,
            "backend_version": BACKEND_VERSION,
            "asset_version": STATIC_ASSET_VERSION,
            "ui_theme": _read_ui_theme(request),
        },
        status_code=status_code,
    )


def _accept_failure_response(
    request: Request,
    db: Session,
    *,
    invite_token: str,
    account_name: str,
    error: str,
    status_code: int,
    current_account_name: str = "",
) -> HTMLResponse:
    try:
        preview = preview_invitation(db, invite_token=invite_token)
    except AppError:
        preview = None
    return _render_join(
        request,
        preview=preview,
        invite_token=invite_token,
        account_name=account_name,
        current_account_name=current_account_name,
        error=error,
        status_code=status_code,
    )


def _restart_anonymous_accept(
    response: Response,
    *,
    clear_invalid_session: bool = False,
) -> None:
    if clear_invalid_session:
        clear_session_cookie(response)
    _set_pairing_attempt_cookie(response, _new_pairing_attempt_cookie())


@router.get("", response_class=HTMLResponse, include_in_schema=False)
def web_invitation_join(request: Request) -> HTMLResponse:
    return _render_join(request)


@router.post("/preview", response_class=HTMLResponse, include_in_schema=False)
def web_invitation_preview(
    request: Request,
    invite_token: str = Form(default=""),
    csrf_token: str = Form(default=""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    try:
        token = _canonical_invite_token(request, invite_token)
        preview = preview_invitation(db, invite_token=token)
    except AppError as exc:
        return _render_join(
            request,
            invite_token=invite_token.strip(),
            error=exc.message,
            status_code=exc.status_code,
        )
    _, principal, invalid_session = _browser_identity(request, db)
    response = _render_join(
        request,
        preview=preview,
        invite_token=token,
        current_account_name=principal.account_name if principal else "",
        error=(
            "登录状态已失效，请确认称呼后再加入。" if invalid_session else ""
        ),
        status_code=401 if invalid_session else 200,
    )
    if principal is None:
        if invalid_session:
            clear_session_cookie(response)
        if _read_pairing_attempt(request) is None:
            _set_pairing_attempt_cookie(response, _new_pairing_attempt_cookie())
    return response


@router.post("/accept", response_class=HTMLResponse, include_in_schema=False)
def web_invitation_accept(
    request: Request,
    invite_token: str = Form(default=""),
    account_name: str = Form(default=""),
    csrf_token: str = Form(default=""),
    db: Session = Depends(get_db),
) -> Response:
    try:
        token = _canonical_invite_token(request, invite_token)
    except AppError as exc:
        return _render_join(
            request,
            invite_token=invite_token.strip(),
            account_name=account_name,
            error=exc.message,
            status_code=exc.status_code,
        )

    session_token, principal, invalid_session = _browser_identity(request, db)
    if invalid_session:
        response = _accept_failure_response(
            request,
            db,
            invite_token=token,
            account_name=account_name,
            error="登录状态已失效，请确认称呼后重新提交。",
            status_code=401,
        )
        _restart_anonymous_accept(response, clear_invalid_session=True)
        return response

    attempt = _read_pairing_attempt(request) if principal is None else None
    if principal is None and attempt is None:
        response = _accept_failure_response(
            request,
            db,
            invite_token=token,
            account_name=account_name,
            error="本次安全确认已失效，请重新提交。",
            status_code=422,
        )
        _restart_anonymous_accept(response)
        return response

    try:
        result = accept_invitation(
            db,
            invite_token=token,
            account_name=None if principal else account_name,
            device_name="浏览器",
            platform="web",
            session_token=session_token if principal else None,
            principal=principal,
            enrollment_attempt_id=attempt[0] if attempt else None,
            enrollment_attempt_secret=attempt[1] if attempt else None,
        )
    except AppError as exc:
        return _accept_failure_response(
            request,
            db,
            invite_token=token,
            account_name=account_name,
            current_account_name=principal.account_name if principal else "",
            error=exc.message,
            status_code=exc.status_code,
        )

    landing_path = "/web/confirmed" if result.role == "viewer" else "/web/pending"
    redirect = RedirectResponse(
        url=_with_ledger(landing_path, result.ledger_id),
        status_code=303,
    )
    if principal is None:
        set_session_cookie(redirect, result.session_token)
        _clear_pairing_attempt_cookie(redirect)
    return redirect
