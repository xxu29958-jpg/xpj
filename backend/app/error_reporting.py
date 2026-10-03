"""Report at existing terminal boundaries without changing business outcomes."""

from __future__ import annotations

import logging
from contextlib import suppress

from starlette.requests import Request

from app.log_sanitize import mask_upload_path


def report_error(logger: logging.Logger, message: str, *args, error: BaseException | None = None) -> None:
    # Failure of the existing log sink must not replace a business outcome.
    with suppress(Exception):
        logger.error(message, *args, exc_info=(type(error), error, error.__traceback__) if error else None,
            stacklevel=2)


def retain_handled_error(request: Request, error: Exception) -> None:
    """A form may keep its failure page; the HTTP boundary still owns reporting."""
    request.state.reporting_error = error


def report_http_error(request: Request, status: int, *, error: Exception | None = None, elapsed_ms: int | None = None) -> None:
    report_error(logging.getLogger("ticketbox.http"),
        "%s %s -> %d request_id=%s elapsed_ms=%s", request.method, mask_upload_path(request.url.path),
        status, getattr(request.state, "request_id", "unavailable"), elapsed_ms,
        error=error or getattr(request.state, "reporting_error", None))
