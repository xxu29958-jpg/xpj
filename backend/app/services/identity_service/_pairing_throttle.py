"""In-process pairing-code rate limiting.

Module-level ``_pairing_failures_by_remote`` is the single instance — Python
caches the module on first import so multiple call sites share the same
dict (intentional; this is process-scoped state, not per-import).
"""

from __future__ import annotations

from datetime import datetime

from app.errors import AppError
from app.services.identity_service._models import (
    PAIRING_ATTEMPT_WINDOW,
    PAIRING_MAX_FAILED_ATTEMPTS,
)
from app.services.time_service import now_utc

_pairing_failures_by_remote: dict[str, list[datetime]] = {}


def _remote_attempt_key(remote_id: str | None) -> str:
    return (remote_id or "unknown").strip() or "unknown"


def _active_pairing_failures(remote_id: str | None, now: datetime) -> list[datetime]:
    key = _remote_attempt_key(remote_id)
    cutoff = now - PAIRING_ATTEMPT_WINDOW
    failures = [failed_at for failed_at in _pairing_failures_by_remote.get(key, []) if failed_at > cutoff]
    if failures:
        _pairing_failures_by_remote[key] = failures
    else:
        _pairing_failures_by_remote.pop(key, None)
    return failures


def _check_pairing_attempt_limit(remote_id: str | None) -> None:
    if len(_active_pairing_failures(remote_id, now_utc())) >= PAIRING_MAX_FAILED_ATTEMPTS:
        raise AppError("invalid_pairing_code", "绑定码尝试次数过多，请稍后再试。", status_code=429)


def _record_pairing_failure(remote_id: str | None) -> None:
    now = now_utc()
    key = _remote_attempt_key(remote_id)
    failures = _active_pairing_failures(remote_id, now)
    failures.append(now)
    _pairing_failures_by_remote[key] = failures


def _clear_pairing_failures(remote_id: str | None) -> None:
    _pairing_failures_by_remote.pop(_remote_attempt_key(remote_id), None)


def _reject_pairing(remote_id: str | None, error: str, status_code: int) -> None:
    _record_pairing_failure(remote_id)
    raise AppError(error, status_code=status_code)
