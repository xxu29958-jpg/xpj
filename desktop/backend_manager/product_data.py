"""Bounded bridge from the Manager loopback UI to the backend.

The browser never receives the app principal. The Manager reads it from
Windows Credential Manager, adds it only to the backend ``Authorization``
header, disables proxy inheritance, and rejects redirects.

Desktop pairing / ledger-switch are two-phase (#219): the client generates
the activation attempt proof, derives the staged credential locally with
the exact KDF the backend applies, and only
``POST /api/auth/desktop/activate`` can promote it. The pending value the
Manager persists is always the client-derived one — never a server-minted
token.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final

from backend_manager.product_identity import ProductSession

_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_LEDGER_COUNT = 200
_PAIRING_CODE_PATTERN = re.compile(r"^\d{8}$")
_LEDGER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_DESKTOP_DEVICE_NAME = "小票夹 Desktop"

# Byte-exact replica of the backend derivation in
# backend/app/services/session_lifecycle_service.py
# (``_derive_attempt_token`` with ``DESKTOP_ACTIVATION_TOKEN_CONTEXT``):
# HMAC-SHA256(key=decoded 256-bit attempt secret,
#             msg=context || UUID(attempt_id).bytes) → "tbx_" + b64url-nopad.
_DESKTOP_ACTIVATION_TOKEN_CONTEXT: Final = b"ticketbox/desktop-activation/v1/session-token\0"
_ATTEMPT_SECRET_BYTES: Final = 32


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


@dataclass(frozen=True)
class PendingProductSession:
    """A staged desktop credential plus its client-owned activation proof.

    ``session.session_token`` is the client-derived pending value and
    ``session.expires_at`` is the staging TTL; after activation the real
    session keeps the same token value with the real app expiry.
    """

    activation_attempt_id: str
    activation_attempt_secret: str = field(repr=False)
    session: ProductSession


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


def new_activation_attempt() -> tuple[str, str]:
    """Generate one client-owned ``(activation_attempt_id, secret)`` proof."""

    attempt_id = str(uuid.uuid4())
    attempt_secret = base64.urlsafe_b64encode(secrets.token_bytes(_ATTEMPT_SECRET_BYTES)).decode("ascii").rstrip("=")
    return attempt_id, attempt_secret


def derive_desktop_pending_token(activation_secret: str, activation_attempt_id: str) -> str:
    """Derive the staged credential — byte-exact with the backend KDF."""

    try:
        raw = base64.urlsafe_b64decode(activation_secret.encode("ascii") + b"=")
    except (UnicodeEncodeError, ValueError) as exc:
        raise ProductDataError(
            "桌面激活凭据无效，请重试绑定。",
            error="invalid_token",
            status_code=401,
        ) from exc
    canonical = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    if len(raw) != _ATTEMPT_SECRET_BYTES or not secrets.compare_digest(canonical, activation_secret):
        raise ProductDataError(
            "桌面激活凭据无效，请重试绑定。",
            error="invalid_token",
            status_code=401,
        )
    try:
        attempt_bytes = uuid.UUID(activation_attempt_id).bytes
    except (ValueError, AttributeError) as exc:
        raise ProductDataError(
            "桌面激活凭据无效，请重试绑定。",
            error="invalid_token",
            status_code=401,
        ) from exc
    digest = hmac.new(raw, _DESKTOP_ACTIVATION_TOKEN_CONTEXT + attempt_bytes, hashlib.sha256).digest()
    return f"tbx_{base64.urlsafe_b64encode(digest).decode('ascii').rstrip('=')}"


def _assert_derived_matches(expected: str, candidate: object) -> str:
    if not isinstance(candidate, str) or not secrets.compare_digest(expected, candidate):
        raise ProductDataError("后端桌面身份合同不完整。")
    return candidate


def pair_product_session(
    backend_origin: str,
    pairing_code: str,
    *,
    timeout_seconds: float,
    device_name: str = _DESKTOP_DEVICE_NAME,
    attempt: tuple[str, str] | None = None,
) -> PendingProductSession:
    """Stage a pending Desktop bearer from one existing 8-digit code."""

    code = pairing_code.strip()
    if not _PAIRING_CODE_PATTERN.fullmatch(code):
        raise ProductDataError(
            "请输入 8 位数字绑定码。",
            error="invalid_pairing_code",
            status_code=400,
        )
    attempt_id, attempt_secret = attempt or new_activation_attempt()
    derived = derive_desktop_pending_token(attempt_secret, attempt_id)
    parsed = _validated_loopback_origin(backend_origin)
    url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/api/auth/pair", "", ""))
    body = json.dumps(
        {
            "pairing_code": code,
            "pairing_attempt_id": attempt_id,
            "pairing_attempt_secret": attempt_secret,
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
    if (
        payload.get("activation_required") is not True
        or payload.get("pairing_attempt_id") != attempt_id
    ):
        raise ProductDataError("后端绑定响应合同不完整。")
    try:
        session = ProductSession(
            session_token=_assert_derived_matches(derived, payload["session_token"]),
            account_name=_required_response_text(payload, "account_name", 120),
            ledger_id=_required_response_text(payload, "ledger_id", 64),
            ledger_name=_required_response_text(payload, "ledger_name", 120),
            device_name=_required_response_text(payload, "device_name", 120),
            role=_required_response_text(payload, "role", 32),
            expires_at=_required_response_text(payload, "activation_expires_at", 64),
        )
    except (KeyError, TypeError) as exc:
        raise ProductDataError("后端绑定响应合同不完整。") from exc
    if session.role not in {"owner", "member", "viewer"}:
        raise ProductDataError("后端绑定响应合同不完整。")
    return PendingProductSession(
        activation_attempt_id=attempt_id,
        activation_attempt_secret=attempt_secret,
        session=session,
    )


def activate_product_session(
    backend_origin: str,
    pending: PendingProductSession,
    previous_session_token: str | None,
    *,
    timeout_seconds: float,
) -> ProductSession:
    """Promote the staged credential via its attempt proof.

    The previous session proof (``X-Ticketbox-Previous-Session``) is only
    valid for a same-ledger re-pair: the backend binds the predecessor to
    the staged credential's account AND ledger, so a ledger switch must
    never send it. Expiry metadata always comes from this activate
    response — never from the stale staged copy.
    """

    derived = derive_desktop_pending_token(
        pending.activation_attempt_secret,
        pending.activation_attempt_id,
    )
    pending_token = _validated_session_token(pending.session.session_token)
    if not secrets.compare_digest(derived, pending_token):
        raise ProductDataError("桌面激活凭据无效，请重试绑定。", error="invalid_token", status_code=401)
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
    body = json.dumps(
        {
            "activation_attempt_id": pending.activation_attempt_id,
            "activation_attempt_secret": pending.activation_attempt_secret,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json; charset=utf-8",
    }
    if previous_token is not None:
        headers["X-Ticketbox-Previous-Session"] = previous_token
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers=headers,
    )
    payload = _read_json_response(
        _opener(),
        request,
        timeout_seconds=timeout_seconds,
    )
    if (
        payload.get("activation_attempt_id") != pending.activation_attempt_id
        or not isinstance(payload.get("activated"), bool)
        or payload.get("ledger_id") != pending.session.ledger_id
    ):
        raise ProductDataError("后端桌面身份激活合同不完整。")
    try:
        return ProductSession(
            session_token=_assert_derived_matches(derived, payload["session_token"]),
            account_name=pending.session.account_name,
            ledger_id=pending.session.ledger_id,
            ledger_name=pending.session.ledger_name,
            device_name=pending.session.device_name,
            role=pending.session.role,
            expires_at=_optional_response_text(payload, "expires_at", 64),
        )
    except (KeyError, TypeError) as exc:
        raise ProductDataError("后端桌面身份激活合同不完整。") from exc


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
    attempt: tuple[str, str] | None = None,
) -> PendingProductSession:
    """Stage a short-lived Desktop token on the target ledger.

    The live token is NOT displaced: promotion happens only via
    :func:`activate_product_session` — which must then be called WITHOUT a
    previous-session proof (the source-ledger credential is not a valid
    predecessor for a cross-ledger activation) and followed by an explicit
    revoke of the old credential.
    """

    target = target_ledger_id.strip()
    if not _LEDGER_ID_PATTERN.fullmatch(target):
        raise ProductDataError(
            "账本标识无效。",
            error="invalid_request",
            status_code=400,
        )
    attempt_id, attempt_secret = attempt or new_activation_attempt()
    derived = derive_desktop_pending_token(attempt_secret, attempt_id)
    parsed = _validated_loopback_origin(backend_origin)
    path = f"/api/ledgers/{urllib.parse.quote(target, safe='')}/switch/prepare"
    url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
    body = json.dumps(
        {
            "activation_attempt_id": attempt_id,
            "activation_attempt_secret": attempt_secret,
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
        session = ProductSession(
            session_token=_assert_derived_matches(derived, payload["session_token"]),
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
    return PendingProductSession(
        activation_attempt_id=attempt_id,
        activation_attempt_secret=attempt_secret,
        session=session,
    )


def revoke_product_session(
    backend_origin: str,
    session_token: str,
    *,
    timeout_seconds: float,
    scope: str | None = None,
) -> None:
    """Revoke one exact app session without placing it in a URL or response.

    ``scope="lineage"`` widens the kill to the credential's staged and
    promoted replacements — reserved for explicit teardown (unpair); the
    default retires only the predecessor and keeps the promoted successor.
    """

    parsed = _validated_loopback_origin(backend_origin)
    query = urllib.parse.urlencode({"scope": scope}) if scope else ""
    url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/desktop/session/revoke", query, ""))
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
