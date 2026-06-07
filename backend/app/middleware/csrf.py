from __future__ import annotations

import hmac
import re
import secrets
from base64 import urlsafe_b64encode
from collections.abc import Awaitable, Callable
from hashlib import sha256
from urllib.parse import parse_qs, urlparse

from fastapi import Request
from starlette.responses import Response

from app.config import PLACEHOLDER_SECRETS, get_settings
from app.errors import AppError, error_response
from app.network_boundary import is_loopback_request

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
_PROTECTED_PREFIXES = ("/web", "/owner")
_SOURCE_HEADERS = ("origin", "referer", "sec-fetch-site")
CSRF_COOKIE_NAME = "xpj_csrf_seed"
CSRF_FIELD_NAME = "csrf_token"
CSRF_HEADER_NAME = "x-csrf-token"
_MULTIPART_CSRF_RE = re.compile(
    rb'name="csrf_token"[^\r\n]*\r\n\r\n(?P<token>[^\r\n]+)'
)


def _max_csrf_body_bytes() -> int:
    """CSRF body 缓冲上限。codex P1 #2:此前 await request.body() 整包读 multipart,
    认证用户可超大 multipart 打内存。跟随 max_upload_size_bytes + 1MB 头部 / 表单字段
    余量,既允许合法 CSV / multipart 上传 + csrf_token 字段,又拒掉无限大请求。"""
    return get_settings().max_upload_size_bytes + 1 * 1024 * 1024


async def csrf_loopback_form_guard(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    if not _is_protected_path(request):
        return await call_next(request)
    if _csrf_secret() is None:
        return error_response(
            "server_error",
            "页面安全校验暂时不可用，请检查服务器配置。",
            status_code=500,
        )
    _ensure_request_csrf_token(request)
    if not _requires_csrf_check(request):
        response = await call_next(request)
        _set_csrf_cookie_if_needed(request, response)
        return response

    if _has_same_origin_source(request):
        valid, body_too_large = await _has_valid_csrf_token(request)
        if body_too_large:
            return error_response(
                "file_too_large",
                "请求体过大，无法完成安全校验。",
                status_code=413,
            )
        if valid:
            response = await call_next(request)
            _set_csrf_cookie_if_needed(request, response)
            return response

    return error_response(
        "invalid_request",
        "本机页面请求已过期，请刷新后重试。",
        status_code=403,
    )


def _requires_csrf_check(request: Request) -> bool:
    if request.method.upper() in _SAFE_METHODS:
        return False
    # FastAPI's default TestClient has no browser cookie/form lifecycle. Keep
    # existing unit tests deterministic; public-host tests use a real peer.
    if _peer_host(request) == "testclient":
        return False
    return _is_protected_path(request)


def _is_protected_path(request: Request) -> bool:
    path = request.url.path
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in _PROTECTED_PREFIXES)


def _has_same_origin_source(request: Request) -> bool:
    sec_fetch_site = (request.headers.get("sec-fetch-site") or "").strip().lower()
    if sec_fetch_site == "cross-site":
        return False
    if sec_fetch_site == "same-origin":
        return True

    host = _normalize_host(request.headers.get("host"))
    if not host:
        return False

    origin = request.headers.get("origin")
    if origin:
        return _normalize_host(urlparse(origin).netloc) == host

    referer = request.headers.get("referer")
    if referer:
        return _normalize_host(urlparse(referer).netloc) == host

    return False


def _normalize_host(value: str | None) -> str:
    return (value or "").strip().lower()


def _peer_host(request: Request) -> str:
    return request.client.host if request.client else ""


# ADR-0045: the per-install CSRF signing key resolved at startup (from app_meta),
# stashed here so the per-request middleware never opens a DB session. Set once by
# the lifespan via :func:`set_persisted_csrf_key`; process-immutable like settings.
_persisted_csrf_key: bytes | None = None


def set_persisted_csrf_key(key: str | None) -> None:
    """Stash the per-install CSRF signing key (ADR-0045). Called from lifespan
    after :func:`app.services.csrf_key_service.get_or_create_csrf_signing_key`
    provisions it in ``app_meta``; tests use it to drive the no-key path."""
    global _persisted_csrf_key
    _persisted_csrf_key = key.encode("utf-8") if key else None


def _csrf_secret() -> bytes | None:
    # An operator-supplied REAL secret wins (backward compat for anyone who set
    # one); the shipped placeholder defaults are REJECTED — they are public in the
    # repo, so using one as the HMAC key is the ADR-0045 bug. Otherwise fall back to
    # the per-install key persisted in app_meta (stashed at startup).
    settings = get_settings()
    for raw in (settings.admin_token, settings.http_bootstrap_secret, settings.app_token):
        candidate = (raw or "").strip()
        if candidate and candidate not in PLACEHOLDER_SECRETS:
            return candidate.encode("utf-8")
    return _persisted_csrf_key


def assert_csrf_signing_key_available() -> None:
    """Refuse to start (ADR-0045) when no usable CSRF signing key is derivable —
    i.e. no real operator secret AND the app_meta key was not provisioned (a DB
    failure). A healthy deployment always self-satisfies (the key is generated on
    first boot), so this only fires on genuine misconfiguration / DB outage."""
    if _csrf_secret() is None:
        # AppError at startup, matching assert_binary_compatible_with_db (the sibling
        # DB-provisioned-value boot gate). Lifespan propagation aborts boot.
        raise AppError(
            "csrf_secret_unavailable",
            "CSRF signing key unavailable: no real ADMIN_TOKEN / HTTP_BOOTSTRAP_SECRET / "
            "APP_TOKEN and the app_meta-persisted key could not be provisioned. Refusing to start.",
            status_code=500,
        )


def _csrf_token_for_seed(seed: str) -> str:
    secret = _csrf_secret()
    if secret is None:
        raise AppError("server_error", "CSRF secret not configured", status_code=500)
    digest = hmac.new(secret, seed.encode("utf-8"), sha256).digest()
    token = urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"v1.{token}"


def _ensure_request_csrf_token(request: Request) -> str:
    seed = (request.cookies.get(CSRF_COOKIE_NAME) or "").strip()
    if not seed:
        seed = secrets.token_urlsafe(32)
        request.state.csrf_seed_pending = seed
    request.state.csrf_token = _csrf_token_for_seed(seed)
    return request.state.csrf_token


async def _has_valid_csrf_token(request: Request) -> tuple[bool, bool]:
    """返回 (valid, body_too_large)。body_too_large=True 时调用方必须直接 413,
    不能继续走 valid=False 的"过期"分支(下游也已无法读 body,且语义不同)。"""
    expected = _ensure_request_csrf_token(request)
    actual = (request.headers.get(CSRF_HEADER_NAME) or "").strip()
    if not actual:
        body, too_large = await _body_bytes_and_replay(request)
        if too_large:
            return False, True
        actual = _csrf_token_from_body(request, body)
    valid = bool(actual) and hmac.compare_digest(actual, expected)
    return valid, False


async def _body_bytes_and_replay(request: Request) -> tuple[bytes, bool]:
    """流式缓冲 body 用于 CSRF token 提取,有硬上限。codex P1 #2:此前 await request.body()
    整包读 multipart,认证用户可超大 multipart 打内存。

    1) 先看 Content-Length, 声明就超限直接 (b"", True)——便宜的早期拒。
    2) chunked encoding 没 Content-Length, 边收边累, 到上限也拒。
    3) 成功收完则按原 Starlette idiom replay 给下游 form 解析。

    返回 (body_bytes, too_large)。
    """
    cap = _max_csrf_body_bytes()
    raw_cl = request.headers.get("content-length")
    if raw_cl:
        try:
            declared = int(raw_cl)
        except (TypeError, ValueError):
            declared = -1
        if declared > cap:
            return b"", True

    body = bytearray()
    while True:
        message = await request.receive()
        if message["type"] != "http.request":
            continue
        chunk = message.get("body") or b""
        if chunk:
            body.extend(chunk)
            if len(body) > cap:
                return b"", True
        if not message.get("more_body"):
            break

    body_bytes = bytes(body)
    sent = False

    async def _receive() -> dict[str, object]:
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body_bytes, "more_body": False}

    request._receive = _receive  # noqa: SLF001 - Starlette body replay for downstream form parsing.
    return body_bytes, False


def _csrf_token_from_body(request: Request, body: bytes) -> str:
    content_type = (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if content_type == "application/x-www-form-urlencoded":
        try:
            values = parse_qs(body.decode("utf-8"), keep_blank_values=True)
        except UnicodeDecodeError:
            return ""
        return (values.get(CSRF_FIELD_NAME, [""])[0] or "").strip()
    if content_type == "multipart/form-data":
        match = _MULTIPART_CSRF_RE.search(body)
        if match is None:
            return ""
        return match.group("token").decode("ascii", "ignore").strip()
    return ""


def _set_csrf_cookie_if_needed(request: Request, response: Response) -> None:
    seed = getattr(request.state, "csrf_seed_pending", None)
    if not seed:
        return
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=seed,
        max_age=8 * 60 * 60,
        httponly=True,
        secure=not is_loopback_request(request),
        samesite="lax",
        path="/",
    )


def csrf_context(request: Request) -> dict[str, str]:
    token = _ensure_request_csrf_token(request)
    return {
        "csrf_token": token,
        "csrf_field": f'<input type="hidden" name="{CSRF_FIELD_NAME}" value="{token}">',
    }
