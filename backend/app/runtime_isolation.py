"""Bounded offload for request-path isolation.

Custom ``async def`` middleware runs on the Uvicorn event-loop thread.
Synchronous PostgreSQL or network work in that path starves every other
request, including ``/api/health``, without replacing the backend PID.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeVar

import anyio
from anyio import CapacityLimiter

logger = logging.getLogger("ticketbox.runtime")

T = TypeVar("T")

AUTH_OFFLOAD_LIMIT = 8
AUTH_OFFLOAD_TIMEOUT_SECONDS = 30.0
SLOW_AUTH_LOG_MS = 500

_auth_limiter = CapacityLimiter(AUTH_OFFLOAD_LIMIT)


class AuthOffloadTimeout(TimeoutError):
    """The bounded auth/session worker did not finish in time."""


def reset_auth_offload_limiter(limit: int = AUTH_OFFLOAD_LIMIT) -> CapacityLimiter:
    """Replace the process limiter. Tests use this to bound saturation cases."""
    global _auth_limiter
    _auth_limiter = CapacityLimiter(limit)
    return _auth_limiter


def _log_slow_auth(operation: str, duration_ms: int, result: str) -> None:
    if duration_ms < SLOW_AUTH_LOG_MS:
        return
    logger.warning(
        "runtime_auth_operation_slow operation=%s duration_ms=%s result=%s",
        operation,
        duration_ms,
        result,
    )


async def run_blocking_auth(operation: str, func: Callable[[], T]) -> T:
    """Run a synchronous auth/session body in a worker that owns its Session.

    ``func`` must create, use, and close any SQLAlchemy Session on this same
    worker.  Live Session objects and lazy ORM instances must not cross back.
    """
    started = time.monotonic()
    result_class = "ok"
    try:
        try:
            with anyio.fail_after(AUTH_OFFLOAD_TIMEOUT_SECONDS):
                return await anyio.to_thread.run_sync(func, limiter=_auth_limiter)
        except TimeoutError as exc:
            result_class = "timeout"
            raise AuthOffloadTimeout(operation) from exc
    except AuthOffloadTimeout:
        raise
    except Exception:
        result_class = "error"
        raise
    finally:
        _log_slow_auth(
            operation,
            int((time.monotonic() - started) * 1000),
            result_class,
        )
