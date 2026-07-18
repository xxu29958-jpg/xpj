"""Bounded bridge from the Manager loopback UI to the backend.

The browser never receives the app principal. The Manager reads it from
Windows Credential Manager, adds it only to the backend ``Authorization``
header, disables proxy inheritance, and rejects redirects. Inbox commands
remain permission/OCC/idempotency-gated by the backend.
"""

from __future__ import annotations

import json
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Final

from backend_manager.product_identity import ProductSession

PRODUCT_WORKSPACES: Final[frozenset[str]] = frozenset({"inbox", "transactions", "obligations", "plans", "insights"})
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_COMMAND_BYTES = 64 * 1024
_MAX_LEDGER_COUNT = 200
_PAIRING_CODE_PATTERN = re.compile(r"^\d{8}$")
_LEDGER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_DESKTOP_DEVICE_NAME = "小票夹 Desktop"


class ProductDataError(RuntimeError):
    """A safe error that the local control server may return to the product UI."""

    def __init__(
        self,
        message: str,
        *,
        error: str = "product_data_unavailable",
        status_code: int = 503,
    ) -> None:
        super().__init__(message)
        self.error = error
        self.status_code = status_code


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def _error_from_http(exc: urllib.error.HTTPError) -> ProductDataError:
    message = "账务数据暂时不可用，请稍后刷新。"
    error = "product_data_unavailable"
    try:
        raw = exc.read(_MAX_RESPONSE_BYTES + 1)
        if len(raw) <= _MAX_RESPONSE_BYTES:
            payload = json.loads(raw.decode("utf-8"))
            if isinstance(payload, Mapping):
                candidate_message = payload.get("message")
                candidate_error = payload.get("error")
                if isinstance(candidate_message, str) and candidate_message.strip():
                    message = candidate_message.strip()
                if isinstance(candidate_error, str) and candidate_error.strip():
                    error = candidate_error.strip()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        pass
    status_code = exc.code if 400 <= exc.code < 500 else 503
    return ProductDataError(message, error=error, status_code=status_code)


def _validated_loopback_origin(backend_origin: str) -> urllib.parse.SplitResult:
    parsed = urllib.parse.urlsplit(backend_origin)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ProductDataError("桌面数据面只能连接本机后端。")
    return parsed


def _validated_session_token(session_token: str) -> str:
    token = session_token.strip()
    if (
        not token
        or len(token) > 512
        or "\r" in token
        or "\n" in token
        or any(character.isspace() for character in token)
    ):
        raise ProductDataError(
            "桌面身份已失效，请重新绑定。",
            error="invalid_token",
            status_code=401,
        )
    return token


def _auth_headers(session_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_validated_session_token(session_token)}",
        "X-Ticketbox-Desktop-Bridge": "v1",
    }


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirect(),
    )


def _read_json_response(
    opener: urllib.request.OpenerDirector,
    request: urllib.request.Request,
    *,
    timeout_seconds: float,
) -> dict:
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            if response.status != 200:
                raise ProductDataError("账务数据暂时不可用，请稍后刷新。")
            content_type = (response.headers.get("Content-Type") or "").lower()
            if "application/json" not in content_type:
                raise ProductDataError("后端返回了无法识别的账务数据。")
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise _error_from_http(exc) from exc
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        raise ProductDataError("无法读取本机账务数据，请稍后刷新。") from exc
    if len(raw) > _MAX_RESPONSE_BYTES:
        raise ProductDataError("账务数据响应超过安全上限。")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductDataError("后端返回了无法识别的账务数据。") from exc
    if not isinstance(payload, dict):
        raise ProductDataError("后端账务数据合同不完整。")
    return payload


def fetch_product_workspace(
    backend_origin: str,
    workspace: str,
    ledger_id: str | None,
    session_token: str,
    *,
    timeout_seconds: float,
) -> dict:
    if workspace not in PRODUCT_WORKSPACES:
        raise ProductDataError(
            "未知的桌面工作区。",
            error="workspace_not_found",
            status_code=404,
        )
    parsed = _validated_loopback_origin(backend_origin)
    query = urllib.parse.urlencode({"ledger_id": ledger_id}) if ledger_id else ""
    path = f"/desktop/workspaces/{urllib.parse.quote(workspace, safe='')}"
    url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, query, ""))
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            **_auth_headers(session_token),
        },
    )
    payload = _read_json_response(_opener(), request, timeout_seconds=timeout_seconds)
    if (
        payload.get("workspace") != workspace
        or not isinstance(payload.get("rows"), list)
        or not isinstance(payload.get("ledgers"), list)
    ):
        raise ProductDataError("后端账务数据合同不完整。")
    return payload


def list_product_ledgers(
    backend_origin: str,
    session_token: str,
    *,
    timeout_seconds: float,
) -> list[dict]:
    """List active memberships visible to the paired account."""

    parsed = _validated_loopback_origin(backend_origin)
    url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/api/ledgers", "", ""))
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            **_auth_headers(session_token),
        },
    )
    payload = _read_json_response(_opener(), request, timeout_seconds=timeout_seconds)
    rows = payload.get("ledgers")
    if not isinstance(rows, list) or len(rows) > _MAX_LEDGER_COUNT:
        raise ProductDataError("后端账本列表合同不完整。")
    ledgers: list[dict] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ProductDataError("后端账本列表合同不完整。")
        ledger_id = _required_response_text(row, "ledger_id", 64)
        if not _LEDGER_ID_PATTERN.fullmatch(ledger_id):
            raise ProductDataError("后端账本列表合同不完整。")
        role = _required_response_text(row, "role", 32)
        if role not in {"owner", "member", "viewer"}:
            raise ProductDataError("后端账本列表合同不完整。")
        is_default = row.get("is_default")
        if not isinstance(is_default, bool):
            raise ProductDataError("后端账本列表合同不完整。")
        ledgers.append(
            {
                "ledger_id": ledger_id,
                "name": _required_response_text(row, "name", 120),
                "role": role,
                "is_default": is_default,
            }
        )
    return ledgers


def switch_product_ledger(
    backend_origin: str,
    target_ledger_id: str,
    session_token: str,
    *,
    timeout_seconds: float,
) -> ProductSession:
    """Prepare a short-lived Desktop token without displacing the live token."""

    target = target_ledger_id.strip()
    if not _LEDGER_ID_PATTERN.fullmatch(target):
        raise ProductDataError(
            "账本标识无效。",
            error="invalid_request",
            status_code=400,
        )
    parsed = _validated_loopback_origin(backend_origin)
    path = f"/api/ledgers/{urllib.parse.quote(target, safe='')}/switch/prepare"
    url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
    request = urllib.request.Request(
        url,
        data=b"",
        method="POST",
        headers={
            "Accept": "application/json",
            **_auth_headers(session_token),
        },
    )
    payload = _read_json_response(_opener(), request, timeout_seconds=timeout_seconds)
    ledger = payload.get("ledger")
    if not isinstance(ledger, Mapping) or payload.get("activation_required") is not True:
        raise ProductDataError("后端账本切换合同不完整。")
    ledger_id = _required_response_text(ledger, "ledger_id", 64)
    if ledger_id != target:
        raise ProductDataError("后端账本切换合同不完整。")
    role = _required_response_text(ledger, "role", 32)
    if role not in {"owner", "member", "viewer"}:
        raise ProductDataError("后端账本切换合同不完整。")
    try:
        return ProductSession(
            session_token=_validated_session_token(payload["session_token"]),
            account_name=_required_response_text(payload, "account_name", 120),
            ledger_id=ledger_id,
            ledger_name=_required_response_text(ledger, "name", 120),
            device_name=_required_response_text(payload, "device_name", 120),
            role=role,
            expires_at=_required_response_text(
                payload,
                "activation_expires_at",
                64,
            ),
        )
    except (KeyError, TypeError) as exc:
        raise ProductDataError("后端账本切换合同不完整。") from exc


def execute_inbox_command(
    backend_origin: str,
    public_id: str,
    ledger_id: str | None,
    payload: Mapping[str, object],
    idempotency_key: str,
    session_token: str,
    *,
    timeout_seconds: float,
) -> dict:
    """Forward one exact Inbox command to the backend-owned mutation service."""

    parsed = _validated_loopback_origin(backend_origin)
    if not public_id or len(public_id) > 64 or "/" in public_id or "\\" in public_id:
        raise ProductDataError(
            "收件标识无效。",
            error="invalid_request",
            status_code=400,
        )
    if not idempotency_key or len(idempotency_key) > 128:
        raise ProductDataError(
            "缺少有效的幂等请求标识。",
            error="idempotency_key_required",
            status_code=422,
        )
    body = json.dumps(
        dict(payload),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(body) > _MAX_COMMAND_BYTES:
        raise ProductDataError(
            "收件操作内容超过安全上限。",
            error="invalid_request",
            status_code=400,
        )
    query = urllib.parse.urlencode({"ledger_id": ledger_id}) if ledger_id else ""
    path = f"/desktop/workspaces/inbox/expenses/{urllib.parse.quote(public_id, safe='')}/commands"
    url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, query, ""))
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "Idempotency-Key": idempotency_key,
            **_auth_headers(session_token),
        },
    )
    response = _read_json_response(_opener(), request, timeout_seconds=timeout_seconds)
    if (
        response.get("action") not in {"save", "confirm", "ignore"}
        or not isinstance(response.get("message"), str)
        or not isinstance(response.get("expense_status"), str)
        or not isinstance(response.get("row_version"), int)
    ):
        raise ProductDataError("后端收件操作合同不完整。")
    return response


def pair_product_session(
    backend_origin: str,
    pairing_code: str,
    *,
    timeout_seconds: float,
    device_name: str = _DESKTOP_DEVICE_NAME,
) -> ProductSession:
    """Prepare a pending Desktop bearer from one existing 8-digit code."""

    code = pairing_code.strip()
    if not _PAIRING_CODE_PATTERN.fullmatch(code):
        raise ProductDataError(
            "请输入 8 位数字绑定码。",
            error="invalid_pairing_code",
            status_code=400,
        )
    parsed = _validated_loopback_origin(backend_origin)
    url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/api/auth/pair", "", ""))
    body = json.dumps(
        {
            "pairing_code": code,
            "device_name": device_name,
            "platform": "desktop",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    payload = _read_json_response(_opener(), request, timeout_seconds=timeout_seconds)
    if payload.get("activation_required") is not True:
        raise ProductDataError("后端绑定响应合同不完整。")
    try:
        return ProductSession(
            session_token=_validated_session_token(payload["session_token"]),
            account_name=_required_response_text(payload, "account_name", 120),
            ledger_id=_required_response_text(payload, "ledger_id", 64),
            ledger_name=_required_response_text(payload, "ledger_name", 120),
            device_name=_required_response_text(payload, "device_name", 120),
            role=_required_response_text(payload, "role", 32),
            expires_at=_required_response_text(
                payload,
                "activation_expires_at",
                64,
            ),
        )
    except (KeyError, TypeError) as exc:
        raise ProductDataError("后端绑定响应合同不完整。") from exc


def activate_product_session(
    backend_origin: str,
    pending: ProductSession,
    previous_session_token: str | None,
    *,
    timeout_seconds: float,
) -> ProductSession:
    """Activate durably stored B, optionally proving and revoking exact A."""

    pending_token = _validated_session_token(pending.session_token)
    previous_token = _validated_session_token(previous_session_token) if previous_session_token is not None else None
    if previous_token is not None and secrets.compare_digest(
        pending_token,
        previous_token,
    ):
        raise ProductDataError(
            "后端未轮换桌面身份，已保留原绑定。",
            error="product_identity_rotation_required",
            status_code=502,
        )
    parsed = _validated_loopback_origin(backend_origin)
    url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/api/auth/desktop/activate", "", ""))
    headers = {
        "Accept": "application/json",
        **_auth_headers(pending_token),
    }
    if previous_token is not None:
        headers["X-Ticketbox-Previous-Session"] = previous_token
    request = urllib.request.Request(
        url,
        data=b"",
        method="POST",
        headers=headers,
    )
    payload = _read_json_response(
        _opener(),
        request,
        timeout_seconds=timeout_seconds,
    )
    if payload.get("activation_required") is not False or payload.get("ledger_id") != pending.ledger_id:
        raise ProductDataError("后端桌面身份激活合同不完整。")
    role = _required_response_text(payload, "role", 32)
    if role not in {"owner", "member", "viewer"}:
        raise ProductDataError("后端桌面身份激活合同不完整。")
    return ProductSession(
        session_token=pending_token,
        account_name=_required_response_text(payload, "account_name", 120),
        ledger_id=pending.ledger_id,
        ledger_name=_required_response_text(payload, "ledger_name", 120),
        device_name=_required_response_text(payload, "device_name", 120),
        role=role,
        expires_at=_optional_response_text(payload, "expires_at", 64),
    )


def _required_response_text(payload: Mapping[str, object], key: str, limit: int) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ProductDataError("后端绑定响应合同不完整。")
    return value.strip()


def _optional_response_text(
    payload: Mapping[str, object],
    key: str,
    limit: int,
) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ProductDataError("后端绑定响应合同不完整。")
    return value.strip()


def revoke_product_session(
    backend_origin: str,
    session_token: str,
    *,
    timeout_seconds: float,
) -> None:
    """Revoke one exact app session without placing it in a URL or response."""

    parsed = _validated_loopback_origin(backend_origin)
    url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/desktop/session/revoke", "", ""))
    request = urllib.request.Request(
        url,
        data=b"",
        method="POST",
        headers={
            "Accept": "application/json",
            **_auth_headers(session_token),
        },
    )
    try:
        with _opener().open(request, timeout=timeout_seconds) as response:
            if response.status != 204:
                raise ProductDataError("无法解除桌面绑定，请稍后重试。")
            if response.read(1):
                raise ProductDataError("后端解除绑定响应合同不完整。")
    except urllib.error.HTTPError as exc:
        raise _error_from_http(exc) from exc
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        raise ProductDataError("无法解除桌面绑定，请稍后重试。") from exc
