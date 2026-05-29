"""DB-backed scheduler leases for multi-worker deployments."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import AppMeta
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

    with SessionLocal() as db:
        row = db.scalar(
            select(AppMeta).where(AppMeta.key == "scheduler_lease:fx_rate_sync")
        )
        assert row is not None
        row.value = (now_utc() - timedelta(seconds=1)).isoformat()
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
