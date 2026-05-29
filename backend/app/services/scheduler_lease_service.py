"""DB-backed leases for process-local daemon schedulers.

Each FastAPI worker starts its own in-process scheduler threads. The scheduled
jobs are idempotent, but cloud or multi-worker deployments should still avoid
duplicate work and duplicate outbound calls. This module provides a small
database lease on top of ``app_meta`` so all workers share one coordination
point without introducing a queue broker.
"""

from __future__ import annotations

import re
from datetime import timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AppMeta
from app.services.time_service import now_utc

_LEASE_KEY_PREFIX = "scheduler_lease:"
_SCHEDULER_NAME_PATTERN = re.compile(r"^[a-z0-9_-]+$")


def _lease_key(name: str) -> str:
    cleaned = name.strip().lower()
    if not _SCHEDULER_NAME_PATTERN.fullmatch(cleaned):
        raise ValueError("scheduler lease name must use [a-z0-9_-]")
    key = f"{_LEASE_KEY_PREFIX}{cleaned}"
    if len(key) > 64:
        raise ValueError("scheduler lease key exceeds app_meta.key length")
    return key


def _ensure_lease_row(db: Session, *, key: str) -> None:
    if db.in_transaction():
        db.commit()
    if db.scalar(select(AppMeta).where(AppMeta.key == key)) is not None:
        db.commit()
        return
    db.add(AppMeta(key=key, value="1970-01-01T00:00:00+00:00", updated_at=now_utc()))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()


def try_claim_scheduler_lease(
    db: Session,
    *,
    name: str,
    lease_seconds: int,
) -> bool:
    """Atomically claim a scheduler lease if the previous lease expired."""

    key = _lease_key(name)
    now = now_utc()
    expires_at = now + timedelta(seconds=max(1, int(lease_seconds)))
    _ensure_lease_row(db, key=key)
    result = db.execute(
        update(AppMeta)
        .where(AppMeta.key == key)
        .where(or_(AppMeta.value.is_(None), AppMeta.value <= now.isoformat()))
        .values(value=expires_at.isoformat(), updated_at=now)
    )
    claimed = int(result.rowcount or 0) == 1
    db.commit()
    return claimed


__all__ = ["try_claim_scheduler_lease"]
