"""DB-backed scheduler leases for multi-worker deployments."""

from __future__ import annotations

import threading
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import AppMeta, SchedulerLease
from app.services.scheduler_lease_service import try_claim_scheduler_lease
from app.services.time_service import now_utc


def test_scheduler_lease_is_shared_across_sessions(*, identity) -> None:
    with SessionLocal() as db:
        assert try_claim_scheduler_lease(
            db,
            name="fx_rate_sync",
            lease_seconds=600,
        )

    with SessionLocal() as db:
        assert not try_claim_scheduler_lease(
            db,
            name="fx_rate_sync",
            lease_seconds=600,
        )

    # Expire the lease via the typed timestamptz column (not an ISO string).
    with SessionLocal() as db:
        lease = db.scalar(
            select(SchedulerLease).where(SchedulerLease.name == "fx_rate_sync")
        )
        assert lease is not None
        lease.expires_at = now_utc() - timedelta(seconds=1)
        db.commit()

    with SessionLocal() as db:
        assert try_claim_scheduler_lease(
            db,
            name="fx_rate_sync",
            lease_seconds=600,
        )


def test_scheduler_lease_rejects_unreviewed_key_names(*, identity) -> None:
    with SessionLocal() as db, pytest.raises(ValueError):
        try_claim_scheduler_lease(
            db,
            name="../fx rate",
            lease_seconds=600,
        )

    # A name longer than the scheduler_leases.name PK (VARCHAR(64)) is rejected
    # up front, not handed to the DB as an opaque truncation error.
    with SessionLocal() as db, pytest.raises(ValueError):
        try_claim_scheduler_lease(
            db,
            name="a" * 65,
            lease_seconds=600,
        )


def test_scheduler_lease_refuses_session_with_inflight_transaction(*, identity) -> None:
    # The lease commits autonomously to coordinate workers. A session carrying
    # uncommitted business work must be rejected (not silently committed), so a
    # future caller cannot accidentally have unrelated work persisted by the
    # lease claim. Convert the "靠纪律" precondition into a machine-enforced one.
    probe_key = "scheduler_lease_probe_uncommitted"
    with SessionLocal() as db:
        db.add(AppMeta(key=probe_key, value="x", updated_at=now_utc()))
        db.flush()  # emits SQL -> session now has an in-flight, uncommitted tx
        assert db.in_transaction()
        with pytest.raises(RuntimeError):
            try_claim_scheduler_lease(
                db,
                name="fx_rate_sync",
                lease_seconds=600,
            )
        db.rollback()

    # The in-flight probe row must not have been committed by the lease claim.
    with SessionLocal() as db:
        assert db.scalar(select(AppMeta).where(AppMeta.key == probe_key)) is None


def test_two_sessions_concurrent_claim_yields_single_winner() -> None:
    """Two workers racing to claim a brand-new lease: exactly one wins.

    The single-statement ``INSERT ... ON CONFLICT (name) DO UPDATE ... WHERE
    expires_at <= now RETURNING name`` is the whole serialization武器. On the
    fresh-row race both threads attempt the INSERT; Postgres lets exactly one
    insert and routes the other into DO UPDATE, where its ``WHERE`` re-checks
    against the just-written future ``expires_at`` and matches nothing. Marked
    real_db (``::test_two_sessions``) so each thread gets a real independent
    connection — one shared savepoint connection cannot model the contention.
    """
    barrier = threading.Barrier(2)
    results: list[bool] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def claim() -> None:
        try:
            barrier.wait(timeout=30)
            with SessionLocal() as db:
                won = try_claim_scheduler_lease(
                    db,
                    name="fx_rate_sync",
                    lease_seconds=600,
                )
            with lock:
                results.append(won)
        except BaseException as exc:  # noqa: BLE001 — surface thread failures to the assert
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=claim) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert all(not thread.is_alive() for thread in threads), "claim thread did not finish"

    assert not errors, f"claim threads raised: {errors}"
    assert sorted(results) == [False, True], (
        f"exactly one concurrent claim must win, got {results}"
    )

    # The winner left a single lease row with a future expiry.
    with SessionLocal() as db:
        lease = db.scalar(
            select(SchedulerLease).where(SchedulerLease.name == "fx_rate_sync")
        )
        assert lease is not None
        assert lease.expires_at > now_utc()
