"""ADR-0042 Slice A: request-idempotency helper unit tests.

Exercises the claim/hit/in_progress/mismatch branches + the stale reclaim and
per-tenant isolation directly against the DB (no HTTP route is wired yet — that
starts in Slice B). The ``identity`` fixture resets + seeds the ``owner`` /
``tester_1`` ledgers so the ``api_idempotency_keys.tenant_id`` FK is satisfied.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import ApiIdempotencyKey
from app.services.idempotency import (
    IDEMPOTENCY_STATUS_IN_PROGRESS,
    IDEMPOTENCY_STATUS_SUCCEEDED,
    IdempotencyOutcomeKind,
    claim_idempotency_key,
    fingerprint_request,
    mark_idempotency_succeeded,
)
from app.services.time_service import now_utc

_FP = "fp-deadbeef"


def _claim(db, *, tenant_id="owner", key="k1", fingerprint=_FP, **kwargs):
    return claim_idempotency_key(
        db,
        tenant_id=tenant_id,
        idempotency_key=key,
        operation="patch_expense",
        request_fingerprint=fingerprint,
        target_type="expense",
        target_id="1",
        **kwargs,
    )


def test_first_claim_proceeds_and_persists_in_progress(identity) -> None:
    with SessionLocal() as db:
        outcome = _claim(db)
        assert outcome.kind == IdempotencyOutcomeKind.PROCEED
        assert outcome.row.status == IDEMPOTENCY_STATUS_IN_PROGRESS
        db.commit()

    with SessionLocal() as db:
        row = db.execute(
            select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == "k1")
        ).scalar_one()
        assert row.tenant_id == "owner"
        assert row.status == IDEMPOTENCY_STATUS_IN_PROGRESS
        assert row.completed_at is None
        assert row.expires_at is not None


def test_succeeded_replay_hits_and_carries_resource(identity) -> None:
    with SessionLocal() as db:
        first = _claim(db)
        assert first.kind == IdempotencyOutcomeKind.PROCEED
        mark_idempotency_succeeded(
            db, first.row, resource_type="expense", resource_id="42"
        )
        db.commit()

    # committed-but-unseen replay: same key + same fingerprint → HIT, no OCC.
    with SessionLocal() as db:
        replay = _claim(db)
        assert replay.kind == IdempotencyOutcomeKind.HIT
        assert replay.row.status == IDEMPOTENCY_STATUS_SUCCEEDED
        assert replay.row.resource_type == "expense"
        assert replay.row.resource_id == "42"


def test_same_key_different_fingerprint_is_mismatch(identity) -> None:
    with SessionLocal() as db:
        first = _claim(db, fingerprint="fp-original")
        mark_idempotency_succeeded(db, first.row, resource_type="expense", resource_id="7")
        db.commit()

    with SessionLocal() as db:
        reused = _claim(db, fingerprint="fp-different")
        assert reused.kind == IdempotencyOutcomeKind.FINGERPRINT_MISMATCH


def test_concurrent_in_progress_key_blocks(identity) -> None:
    # Unit-scope: drives the conflict-classification branch (insert → unique
    # conflict → re-read existing in_progress) via a COMMITTED prior claim, NOT
    # true parallel execution. Real two-request contention is the deferred
    # PG-lane Confirmation test (ADR §Confirmation).
    # First claim wins but has NOT recorded success yet (still in_progress).
    with SessionLocal() as db:
        first = _claim(db, key="k-busy")
        assert first.kind == IdempotencyOutcomeKind.PROCEED
        db.commit()

    # A second claim for the same key while it's still in_progress is blocked.
    with SessionLocal() as db:
        second = _claim(db, key="k-busy")
        assert second.kind == IdempotencyOutcomeKind.IN_PROGRESS


def test_stale_in_progress_same_fingerprint_is_reclaimed(identity) -> None:
    # A legit retry of the SAME request (same fingerprint) whose owner crashed:
    # the stale placeholder is reclaimed → PROCEED.
    with SessionLocal() as db:
        first = _claim(db, key="k-stale", fingerprint="fp-stale")
        assert first.kind == IdempotencyOutcomeKind.PROCEED
        db.commit()

    # Simulate the original owner crashing: age the placeholder past the window.
    with SessionLocal() as db:
        row = db.execute(
            select(ApiIdempotencyKey).where(
                ApiIdempotencyKey.idempotency_key == "k-stale"
            )
        ).scalar_one()
        row.created_at = now_utc() - timedelta(hours=1)
        db.commit()

    with SessionLocal() as db:
        retry = _claim(db, key="k-stale", fingerprint="fp-stale")
        assert retry.kind == IdempotencyOutcomeKind.PROCEED
        db.commit()


def test_stale_in_progress_different_fingerprint_is_mismatch(identity) -> None:
    # §4.7: a stale placeholder must NOT be silently reclaimed by a DIFFERENT
    # request reusing the key — that's idempotency_key_reused, not a fresh claim.
    with SessionLocal() as db:
        first = _claim(db, key="k-stale-reuse", fingerprint="fp-a")
        assert first.kind == IdempotencyOutcomeKind.PROCEED
        db.commit()

    with SessionLocal() as db:
        row = db.execute(
            select(ApiIdempotencyKey).where(
                ApiIdempotencyKey.idempotency_key == "k-stale-reuse"
            )
        ).scalar_one()
        row.created_at = now_utc() - timedelta(hours=1)
        db.commit()

    with SessionLocal() as db:
        reused = _claim(db, key="k-stale-reuse", fingerprint="fp-b")
        assert reused.kind == IdempotencyOutcomeKind.FINGERPRINT_MISMATCH
        db.commit()


def test_in_progress_different_fingerprint_is_mismatch(identity) -> None:
    # §4.7: a different request reusing an IN-FLIGHT key (not yet stale) is reuse
    # too — FINGERPRINT_MISMATCH (→ 422), not "retry later".
    with SessionLocal() as db:
        first = _claim(db, key="k-inflight-reuse", fingerprint="fp-a")
        assert first.kind == IdempotencyOutcomeKind.PROCEED
        db.commit()

    with SessionLocal() as db:
        reused = _claim(db, key="k-inflight-reuse", fingerprint="fp-b")
        assert reused.kind == IdempotencyOutcomeKind.FINGERPRINT_MISMATCH
        db.commit()


def test_fresh_in_progress_not_reclaimed_with_zero_window(identity) -> None:
    # A non-stale in_progress (well within the window) must stay blocked, never
    # reclaimed — the negative guard for test_stale_in_progress_is_reclaimed.
    with SessionLocal() as db:
        first = _claim(db, key="k-fresh")
        assert first.kind == IdempotencyOutcomeKind.PROCEED
        db.commit()

    with SessionLocal() as db:
        second = _claim(
            db, key="k-fresh", stale_in_progress_after=timedelta(minutes=10)
        )
        assert second.kind == IdempotencyOutcomeKind.IN_PROGRESS


def test_same_key_distinct_per_tenant(identity) -> None:
    # The unique constraint is (tenant_id, idempotency_key): the same client UUID
    # under two ledgers stays independent (ADR-0042 §4.1).
    with SessionLocal() as db:
        owner_claim = _claim(db, tenant_id="owner", key="shared-key")
        assert owner_claim.kind == IdempotencyOutcomeKind.PROCEED
        db.commit()

    with SessionLocal() as db:
        tester_claim = _claim(db, tenant_id="tester_1", key="shared-key")
        assert tester_claim.kind == IdempotencyOutcomeKind.PROCEED
        db.commit()


def test_rolled_back_claim_does_not_block_retry(identity) -> None:
    # ADR-0042 §4.9: a caller that aborts after claiming (validation error, OCC
    # 409, permission, pre-commit 5xx) must leave NO blocking in_progress row —
    # the next legitimate retry must PROCEED, not get stuck behind a stale
    # placeholder. Regression for the SQLite SAVEPOINT-autocommit trap: a
    # `begin_nested()` with no real outer writer transaction would RELEASE-commit
    # the placeholder so the caller rollback couldn't undo it.
    with SessionLocal() as db:
        # Mirror a real route: an auth-context read runs before the claim, so the
        # session is already in a (read) transaction when claim_idempotency_key
        # is called — the exact shape that triggers the trap.
        db.execute(select(ApiIdempotencyKey).limit(1)).all()
        first = _claim(db, key="k-rollback")
        assert first.kind == IdempotencyOutcomeKind.PROCEED
        db.rollback()  # caller aborts without committing

    with SessionLocal() as db:
        retry = _claim(db, key="k-rollback")
        assert retry.kind == IdempotencyOutcomeKind.PROCEED, (
            "a rolled-back claim must not leave a blocking in_progress row"
        )
        db.commit()


@pytest.mark.sqlite_only
def test_claim_rejects_pending_writes_before_claim(identity) -> None:
    # ADR §4.4: the claim must be the request's FIRST write. The SQLite writer-
    # transaction guard commits the prior (read-only) tx — if a caller violated
    # the contract and has uncommitted WRITES staged, the guard must fail loudly
    # rather than silently commit them before the OCC / idempotency outcome is
    # known. (Postgres has no such commit, so this is a SQLite-lane guard.)
    with SessionLocal() as db:
        db.execute(select(ApiIdempotencyKey).limit(1)).all()  # start a read tx
        db.add(
            ApiIdempotencyKey(
                tenant_id="owner",
                idempotency_key="pending-write",
                operation="x",
                request_fingerprint="fp",
                status=IDEMPOTENCY_STATUS_IN_PROGRESS,
                created_at=now_utc(),
                expires_at=now_utc() + timedelta(days=1),
            )
        )  # an uncommitted write staged BEFORE the claim
        with pytest.raises(AssertionError):
            _claim(db, key="k-guard")
        db.rollback()


def test_fingerprint_is_deterministic_and_sensitive() -> None:
    base = {"operation": "patch_expense", "target_id": "1", "body": {"category": "餐饮"}}
    fp1 = fingerprint_request(**base, expected_row_version=3)
    fp2 = fingerprint_request(**base, expected_row_version=3)
    assert fp1 == fp2  # deterministic

    # expected_row_version is part of the fingerprint (KeepMine rotates a key).
    assert fingerprint_request(**base, expected_row_version=4) != fp1
    # body changes the fingerprint.
    assert (
        fingerprint_request(
            operation="patch_expense",
            target_id="1",
            body={"category": "购物"},
            expected_row_version=3,
        )
        != fp1
    )
