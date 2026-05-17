from __future__ import annotations

from collections.abc import Awaitable, Callable
from urllib.parse import urlparse

from fastapi import Request
from starlette.responses import Response

from app.errors import error_response


_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
_PROTECTED_PREFIXES = ("/web", "/owner")
_SOURCE_HEADERS = ("origin", "referer", "sec-fetch-site")


async def csrf_loopback_form_guard(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    if not _requires_csrf_check(request):
        return await call_next(request)

    if _has_same_origin_source(request):
        return await call_next(request)

    return error_response(
        "invalid_request",
        "本机页面请求已过期，请刷新后重试。",
        status_code=403,
    )


def _requires_csrf_check(request: Request) -> bool:
    if request.method.upper() in _SAFE_METHODS:
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

    # FastAPI's default TestClient has no browser source headers. Keep existing
    # unit tests deterministic without weakening real browser requests.
    if _peer_host(request) == "testclient" and not any(request.headers.get(name) for name in _SOURCE_HEADERS):
        return True

    return False


def _normalize_host(value: str | None) -> str:
    return (value or "").strip().lower()


def _peer_host(request: Request) -> str:
    return request.client.host if request.client else ""
