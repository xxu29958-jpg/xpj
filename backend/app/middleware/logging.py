"""Lightweight logging middleware for the backend.

Goals:
- Mask upload keys in /u/{key} paths before any log output.
- Never collect authentication/cookie headers.
- Never log request bodies.
- Never log absolute Windows filesystem paths in error responses.
- Not add noisy per-request access logs; only log on 5xx or for debug mode.
- Attach a per-request opaque id (X-Request-Id) so 5xx log lines and error
  response bodies can be correlated — see ENGINEERING_RULES §12 "错误日志
  必须带 request_id / trace_id".

This middleware is intentionally minimal. It uses Python's standard
``logging`` module (not uvicorn access logs). Uvicorn access logs are
disabled by default.
"""

from __future__ import annotations

import re
import secrets
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.error_reporting import report_http_error

REQUEST_ID_HEADER = "X-Request-Id"


def _new_request_id() -> str:
    # 16-char hex (8 bytes of entropy) — opaque to clients, cheap to generate,
    # short enough to paste into a chat/screenshot when reporting a failure.
    return secrets.token_hex(8)


class SanitizedLoggingMiddleware(BaseHTTPMiddleware):
    """Report 5xx with a masked path, request ID and retained error. Silent on 2xx/3xx/4xx.

    Per-request flow:

    1. Generate ``request_id`` (or honor an incoming ``X-Request-Id`` if the
       caller already set one — useful when an Android/desktop client wants
       to correlate its own log line with the backend).
    2. Stash on ``request.state.request_id`` so the exception handlers in
       :mod:`app.errors` can echo it into error response bodies.
    3. Set ``X-Request-Id`` on every outgoing response.
    4. On 5xx, include ``request_id`` in the structured log line.
    """

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        incoming = request.headers.get(REQUEST_ID_HEADER, "").strip()
        request_id = incoming if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", incoming) else _new_request_id()
        request.state.request_id = request_id

        start = time.monotonic()
        response = await call_next(request)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        response.headers[REQUEST_ID_HEADER] = request_id

        status = response.status_code
        if status >= 500:
            report_http_error(request, status, elapsed_ms=elapsed_ms)
        return response
