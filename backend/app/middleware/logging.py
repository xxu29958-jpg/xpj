"""Lightweight logging middleware for the backend.

Goals:
- Mask upload keys in /u/{key} paths before any log output.
- Redact Authorization, X-Bootstrap-Secret, cookie, upload-token headers.
- Never log request bodies.
- Never log absolute Windows filesystem paths in error responses.
- Not add noisy per-request access logs; only log on 5xx or for debug mode.

This middleware is intentionally minimal. It uses Python's standard
``logging`` module (not uvicorn access logs). Uvicorn access logs are
disabled by default.
"""

from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.log_sanitize import mask_upload_path, safe_headers

logger = logging.getLogger("ticketbox.http")


class SanitizedLoggingMiddleware(BaseHTTPMiddleware):
    """Log 5xx responses with sanitized path/headers. Silent on 2xx/3xx/4xx."""

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        start = time.monotonic()
        response = await call_next(request)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        status = response.status_code
        if status >= 500:
            safe_path = mask_upload_path(request.url.path)
            safe_hdrs = safe_headers(dict(request.headers))
            logger.error(
                "%s %s -> %d (%dms) headers=%s",
                request.method,
                safe_path,
                status,
                elapsed_ms,
                safe_hdrs,
            )
        return response
