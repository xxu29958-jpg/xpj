"""DB-backed pairing-code rate limiting (v1.1 Batch 1).

Previously this module held failures in a process-local dict — restart
the backend, throttle resets; spawn multiple workers, each one has its
own counter. v1.1 moves the state into ``pairing_attempt_failures`` so
the limit survives both.

Public surface is unchanged from the pre-v1.1 module:
``_check_pairing_attempt_limit`` / ``_record_pairing_failure`` /
``_clear_pairing_failures`` / ``_reject_pairing`` all take an optional
``remote_id`` (now also a DB session). Callers pass the session through;
``_pair.py`` already had a session in hand.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import PairingAttemptFailure
from app.services.identity_service._models import (
    PAIRING_ATTEMPT_WINDOW,
    PAIRING_MAX_FAILED_ATTEMPTS,
)
from app.services.time_service import now_utc


def _remote_attempt_key(remote_id: str | None) -> str:
    return (remote_id or "unknown").strip() or "unknown"


def _active_failure_count(db: Session, remote_key: str, now: datetime) -> int:
    cutoff = now - PAIRING_ATTEMPT_WINDOW
    # Prune anything older than the window — keeps the table tiny even
    # under sustained probing because failed_at < cutoff rows are
    # dropped on every check.
    db.execute(
        delete(PairingAttemptFailure)
        .where(PairingAttemptFailure.remote_key == remote_key)
        .where(PairingAttemptFailure.failed_at < cutoff)
    )
    rows = db.scalars(
        select(PairingAttemptFailure.id)
        .where(PairingAttemptFailure.remote_key == remote_key)
        .where(PairingAttemptFailure.failed_at >= cutoff)
    ).all()
    return len(rows)


def _check_pairing_attempt_limit(db: Session, remote_id: str | None) -> None:
    key = _remote_attempt_key(remote_id)
    count = _active_failure_count(db, key, now_utc())
    if count >= PAIRING_MAX_FAILED_ATTEMPTS:
        # §4 generic throttle code. Historically this 429 reused
        # ``invalid_pairing_code``, which clients render as "绑定码无效，
        # 请重新获取" — a dead loop for the user (the code may be perfectly
        # fine; trying again is exactly what makes it worse). The message
        # comes from ERROR_MESSAGES; the invalid/expired/used 401 collapse
        # in _pair.py is unchanged (still non-oracle).
        raise AppError("rate_limited", status_code=429)


def _record_pairing_failure(db: Session, remote_id: str | None) -> None:
    key = _remote_attempt_key(remote_id)
    db.add(PairingAttemptFailure(remote_key=key, failed_at=now_utc()))
    db.commit()


def _clear_pairing_failures(db: Session, remote_id: str | None) -> None:
    key = _remote_attempt_key(remote_id)
    db.execute(
        delete(PairingAttemptFailure).where(
            PairingAttemptFailure.remote_key == key
        )
    )
    db.commit()


def _reject_pairing(
    db: Session,
    remote_id: str | None,
    error: str,
    status_code: int,
) -> None:
    _record_pairing_failure(db, remote_id)
    raise AppError(error, status_code=status_code)
