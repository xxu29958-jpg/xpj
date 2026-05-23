"""Security response headers for public web/API surfaces."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response

from app.network_boundary import is_loopback_request

_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


def _is_web_or_api(path: str) -> bool:
    return path == "/web" or path.startswith("/web/") or path == "/api" or path.startswith("/api/")


def _is_sensitive_cache_path(path: str) -> bool:
    return (
        path == "/web"
        or path.startswith("/web/")
        or (path.startswith("/api/expenses/") and (path.endswith("/image") or path.endswith("/thumbnail")))
    )


async def security_headers(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    response = await call_next(request)
    path = request.url.path
    if _is_web_or_api(path):
        response.headers.setdefault("Content-Security-Policy", _CSP)
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
    if _is_sensitive_cache_path(path):
        response.headers["Cache-Control"] = "no-store"
    if not is_loopback_request(request):
        response.headers.setdefault("Strict-Transport-Security", "max-age=15552000; includeSubDomains")
    return response


__all__ = ["security_headers"]
