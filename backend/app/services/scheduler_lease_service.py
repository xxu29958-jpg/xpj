"""DB-backed leases for process-local daemon schedulers.

Each FastAPI worker starts its own in-process scheduler threads. The scheduled
jobs are idempotent, but cloud or multi-worker deployments should still avoid
duplicate work and duplicate outbound calls. This module claims a lease on the
``scheduler_leases`` table so all workers share one coordination point without
introducing a queue broker.

Atomic claim: the whole claim is a single ``INSERT ... ON CONFLICT (name) DO
UPDATE ... WHERE scheduler_leases.expires_at <= :now RETURNING name``. A returned
row means this worker won the lease; an empty result means another worker holds
an unexpired lease. There is no separate "ensure the row exists" step, so two
workers racing on a fresh or expired lease can never both win — Postgres
serializes the conflicting upsert on the row and the loser's ``WHERE`` re-checks
against the just-written future ``expires_at``.

``expires_at`` is a real ``timestamptz``, so the claim compares times by type
rather than by the UTC-ISO ASCII lexicographic coincidence the prior ``app_meta``
string value relied on.

Transaction contract: the lease coordinates across workers by committing
autonomously, so it must own its session's transaction lifecycle. Callers pass
a session with **no in-flight transaction** (commit or roll back business work
first); ``try_claim_scheduler_lease`` raises ``RuntimeError`` on a session that
already carries uncommitted work instead of silently committing it. Every
in-tree caller claims on a dedicated short-lived session
(``with SessionLocal() as db: try_claim_scheduler_lease(db, ...)``).
"""

from __future__ import annotations

import re
from datetime import timedelta

from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session

from app.models import SchedulerLease
from app.services.time_service import now_utc

_SCHEDULER_NAME_PATTERN = re.compile(r"^[a-z0-9_-]+$")
# scheduler_leases.name is the VARCHAR(64) primary key.
_MAX_LEASE_NAME_LENGTH = 64


def _clean_lease_name(name: str) -> str:
    cleaned = name.strip().lower()
    if not _SCHEDULER_NAME_PATTERN.fullmatch(cleaned):
        raise ValueError("scheduler lease name must use [a-z0-9_-]")
    if len(cleaned) > _MAX_LEASE_NAME_LENGTH:
        raise ValueError("scheduler lease name exceeds scheduler_leases.name length")
    return cleaned


def try_claim_scheduler_lease(
    db: Session,
    *,
    name: str,
    lease_seconds: int,
) -> bool:
    """Atomically claim a scheduler lease if the previous lease expired.

    ``db`` must have no in-flight transaction: the lease commits autonomously to
    coordinate workers, so a session carrying uncommitted business work would
    have that work silently committed. Such a session is rejected with
    ``RuntimeError`` — commit or roll back caller work before claiming.
    """

    if db.in_transaction():
        raise RuntimeError(
            "scheduler lease must be claimed on a session with no in-flight "
            "transaction; commit or roll back caller work before claiming"
        )
    lease_name = _clean_lease_name(name)
    now = now_utc()
    expires_at = now + timedelta(seconds=max(1, int(lease_seconds)))
    statement = (
        postgresql_insert(SchedulerLease)
        .values(name=lease_name, expires_at=expires_at, updated_at=now)
        .on_conflict_do_update(
            index_elements=["name"],
            set_={"expires_at": expires_at, "updated_at": now},
            where=SchedulerLease.expires_at <= now,
        )
        .returning(SchedulerLease.name)
    )
    claimed = db.execute(statement).first() is not None
    db.commit()
    return claimed


__all__ = ["try_claim_scheduler_lease"]
