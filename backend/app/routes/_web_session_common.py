"""Session, ledger-selection, and redirect helpers shared by ``/web`` routes."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from urllib.parse import unquote, urlencode, urlsplit, urlunsplit

from fastapi import Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.errors import AppError
from app.network_boundary import require_owner_console_local
from app.services import owner_console_service as owner_svc
from app.services.ledger_service import find_owner_account_id_for_ledger


def parse_form_row_version_token(value: str) -> int | None:
    """Parse the integer OCC token carried by hidden Web form fields."""

    cleaned = (value or "").strip()
    if not cleaned:
        return None
    try:
        parsed = int(cleaned)
        return parsed if parsed > 0 else None
    except ValueError:
        return None


def _require_local(request: Request) -> None:
    """Accept a verified Web session or require the loopback owner boundary."""

    if getattr(request.state, "web_session_auth", None) is not None:
        return
    require_owner_console_local(request)


LocalOnly = Depends(_require_local)


def resolve_web_actor(
    db: Session,
    request: Request,
    ledger_id: str,
) -> tuple[int, int | None]:
    """Resolve the accountable account/device pair for a Web mutation."""

    session_auth = getattr(request.state, "web_session_auth", None)
    if session_auth is not None:
        if session_auth.ledger_id != ledger_id:
            raise AppError("permission_denied", status_code=403)
        return session_auth.account_id, session_auth.device_id
    account_id = find_owner_account_id_for_ledger(db, ledger_id=ledger_id)
    if account_id is None:
        raise AppError(
            "permission_denied",
            "当前账本没有可记录的操作账号。",
            status_code=403,
        )
    return account_id, None


def resolve_web_actor_account_id(
    db: Session,
    request: Request,
    ledger_id: str,
) -> int:
    """Compatibility projection for commands that only record an account."""

    return resolve_web_actor(db, request, ledger_id)[0]


@dataclass
class LedgerOption:
    """Option row for the ``/web`` ledger selector. Safe to render in HTML."""

    ledger_id: str
    name: str
    role: str
    is_default: bool
    pending_count: int
    confirmed_count: int


def _list_ledger_options(db: Session) -> list[LedgerOption]:
    return [
        LedgerOption(
            ledger_id=row.ledger_id,
            name=row.name,
            role=row.role,
            is_default=row.is_default,
            pending_count=row.pending_count,
            confirmed_count=row.confirmed_count,
        )
        for row in owner_svc.list_console_ledgers(db)
    ]


def _project_session_ledger_options(
    options: list[LedgerOption] | None,
    session_auth,
) -> None:
    """Project a public Web session to its single authorized ledger."""

    if options is None:
        return
    matched = next(
        (opt for opt in options if opt.ledger_id == session_auth.ledger_id),
        None,
    )
    options[:] = [
        LedgerOption(
            ledger_id=session_auth.ledger_id,
            name=session_auth.ledger_name,
            role=session_auth.role,
            is_default=matched.is_default if matched is not None else False,
            pending_count=matched.pending_count if matched is not None else 0,
            confirmed_count=matched.confirmed_count if matched is not None else 0,
        )
    ]


def _scope_options_for_desktop_session(
    options: list[LedgerOption] | None,
    session_auth,
) -> None:
    """Replace a desktop bridge session's options with its bound ledger."""

    if options is None:
        return
    scoped = [opt for opt in options if opt.ledger_id == session_auth.ledger_id]
    if not scoped:
        scoped = [
            LedgerOption(
                ledger_id=session_auth.ledger_id,
                name=session_auth.ledger_name,
                role=session_auth.role,
                is_default=False,
                pending_count=0,
                confirmed_count=0,
            )
        ]
    options[:] = scoped


def _revalidate_desktop_session_under_lock(
    db: Session,
    request: Request,
    session_auth,
) -> str:
    """Delegate lock-time desktop-principal revalidation to its service."""

    from app.services.desktop_switch_service import (
        revalidate_desktop_session_under_lock as _service_revalidate,
    )

    mutation = request.method.upper() not in {"GET", "HEAD", "OPTIONS"}
    return _service_revalidate(db, session_auth, mutation=mutation)


def _resolve_selected_ledger_id(
    db: Session,
    requested: str | None,
    options: list[LedgerOption] | None = None,
    *,
    request: Request | None = None,
) -> str:
    """Resolve a ledger only from the authenticated or locally visible scope."""

    if request is not None:
        session_auth = getattr(request.state, "web_session_auth", None)
        if session_auth is not None:
            if getattr(request.state, "web_session_platform", "") == "desktop":
                _scope_options_for_desktop_session(options, session_auth)
                live_role = _revalidate_desktop_session_under_lock(
                    db,
                    request,
                    session_auth,
                )
                session_auth = dataclasses.replace(session_auth, role=live_role)
                request.state.web_session_auth = session_auth
            _project_session_ledger_options(options, session_auth)
            return session_auth.ledger_id

    opts = options if options is not None else _list_ledger_options(db)
    if not opts:
        raise AppError(
            "invalid_request",
            "服务尚未初始化，请先运行本机的 bootstrap 脚本。",
            status_code=400,
        )
    visible_ids = {opt.ledger_id for opt in opts}
    if requested is None or requested == "":
        for opt in opts:
            if opt.is_default:
                return opt.ledger_id
        return opts[0].ledger_id
    if requested not in visible_ids:
        raise AppError(
            "invalid_request",
            "请选择一个有权限的账本。",
            status_code=400,
        )
    return requested


def _selected_option(options: list[LedgerOption], ledger_id: str) -> LedgerOption:
    for opt in options:
        if opt.ledger_id == ledger_id:
            return opt
    return options[0]


def _require_selected_ledger_write(
    options: list[LedgerOption],
    ledger_id: str,
) -> None:
    selected = next((opt for opt in options if opt.ledger_id == ledger_id), None)
    if selected is None or selected.role not in {"owner", "member"}:
        raise AppError(
            "permission_denied",
            "当前角色为只读，无法修改账本。",
            status_code=403,
        )


def _with_ledger(path: str, ledger_id: str, **extra: str) -> str:
    params: dict[str, str] = {"ledger_id": ledger_id}
    for key, value in extra.items():
        if value:
            params[key] = value
    return _safe_same_site_redirect_path(
        f"{path}?{urlencode(params)}",
        fallback="/web",
    )


def _web_redirect(path: str, ledger_id: str, **extra: str) -> RedirectResponse:
    return RedirectResponse(
        url=_with_ledger(path, ledger_id, **extra),
        status_code=303,
    )


def _safe_same_site_redirect_path(
    raw: str | None,
    *,
    allowed_roots: tuple[str, ...] = ("/web",),
    fallback: str = "",
) -> str:
    """Normalize server-side redirects to same-site paths only."""

    if not raw:
        return fallback
    candidate = raw.strip()
    if not candidate or any(ch in candidate for ch in ("\\", "\n", "\r", "\t")):
        return fallback
    if candidate.startswith("//"):
        return fallback

    parsed = urlsplit(candidate)
    if parsed.scheme or parsed.netloc:
        return fallback

    path = parsed.path or ""
    decoded_path = unquote(path)
    if (
        not path.startswith("/")
        or decoded_path.startswith("//")
        or "\\" in decoded_path
        or ":" in decoded_path
    ):
        return fallback
    if any(decoded_path.startswith(root + "//") for root in allowed_roots):
        return fallback
    if not any(
        decoded_path == root or decoded_path.startswith(root + "/")
        for root in allowed_roots
    ):
        return fallback
    return urlunsplit(("", "", path, parsed.query, ""))
