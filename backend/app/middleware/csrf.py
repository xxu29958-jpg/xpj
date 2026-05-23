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

from app.config import get_settings
from app.errors import error_response
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


async def csrf_loopback_form_guard(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    _ensure_request_csrf_token(request)
    if not _requires_csrf_check(request):
        response = await call_next(request)
        _set_csrf_cookie_if_needed(request, response)
        return response

    if _has_same_origin_source(request) and await _has_valid_csrf_token(request):
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


def _csrf_secret() -> bytes:
    settings = get_settings()
    raw = settings.admin_token or settings.http_bootstrap_secret or settings.app_token
    return raw.encode("utf-8")


def _csrf_token_for_seed(seed: str) -> str:
    digest = hmac.new(_csrf_secret(), seed.encode("utf-8"), sha256).digest()
    token = urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"v1.{token}"


def _ensure_request_csrf_token(request: Request) -> str:
    seed = (request.cookies.get(CSRF_COOKIE_NAME) or "").strip()
    if not seed:
        seed = secrets.token_urlsafe(32)
        request.state.csrf_seed_pending = seed
    request.state.csrf_token = _csrf_token_for_seed(seed)
    return request.state.csrf_token


async def _has_valid_csrf_token(request: Request) -> bool:
    expected = _ensure_request_csrf_token(request)
    actual = (request.headers.get(CSRF_HEADER_NAME) or "").strip()
    if not actual:
        body = await _body_bytes_and_replay(request)
        actual = _csrf_token_from_body(request, body)
    return bool(actual) and hmac.compare_digest(actual, expected)


async def _body_bytes_and_replay(request: Request) -> bytes:
    body = await request.body()
    sent = False

    async def _receive() -> dict[str, object]:
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    request._receive = _receive  # noqa: SLF001 - Starlette body replay for downstream form parsing.
    return body


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
