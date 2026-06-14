"""ADR-0042 request-idempotency helper over ``api_idempotency_keys``.

Closes the *committed-but-unseen* gap: a direct mutate request can commit
server-side and have its response lost on the wire; the client then replays
(via the offline outbox) with a now-stale ``expected_row_version`` and the OCC
predicate false-409s it. OCC (``row_version``) protects *concurrent writes*;
this layer protects *safe replay of the same operation* — they are distinct
mechanisms, not substitutes (OCC does not make a request idempotent).

Server ordering (ADR-0042 §4.4): claim the key BEFORE the OCC ``row_version``
claim.

* :func:`claim_idempotency_key` atomically inserts an ``in_progress`` row, or —
  on unique conflict — reads the existing one and classifies it:
    - ``PROCEED``              caller won the claim → run the mutation, then call
                              :func:`mark_idempotency_succeeded` in the SAME
                              transaction.
    - ``HIT``                 key already ``succeeded`` with a matching
                              fingerprint → caller skips the OCC claim and
                              re-serialises the resource's canonical current
                              state from ``resource_type``/``resource_id``
                              (ADR-0042 §4.6); this is what kills the false-409.
    - ``IN_PROGRESS``         a concurrent same-key request holds the claim →
                              caller returns 409 ``idempotency_key_in_progress``.
    - ``FINGERPRINT_MISMATCH`` same key, different request → caller returns 422
                              ``idempotency_key_reused``.
* :func:`mark_idempotency_succeeded` flips ``in_progress`` → ``succeeded`` and
  records where the mutated resource lives. The caller commits it together with
  the business mutation, so "mutation committed but key not recorded" (and the
  inverse) are impossible (§4.5).

Only *committed-success* is ever recorded — validation / OCC-409 / permission /
pre-commit-5xx leave no ``succeeded`` row, so a later legitimate retry still
runs (§4.9). This is an outbox mutation-dedupe table, NOT a Stripe-style generic
response cache (we never cache error responses or response bytes).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import ApiIdempotencyKey
from app.services.time_service import ensure_utc, now_utc

__all__ = [
    "DEFAULT_IDEMPOTENCY_RETENTION",
    "DEFAULT_STALE_IN_PROGRESS",
    "IDEMPOTENCY_STATUS_IN_PROGRESS",
    "IDEMPOTENCY_STATUS_SUCCEEDED",
    "IdempotencyOutcome",
    "IdempotencyOutcomeKind",
    "claim_idempotency_key",
    "claim_idempotent_request",
    "fingerprint_request",
    "mark_idempotency_succeeded",
    "reject_idempotency_target_mismatch",
]

IDEMPOTENCY_STATUS_IN_PROGRESS = "in_progress"
IDEMPOTENCY_STATUS_SUCCEEDED = "succeeded"

# ADR-0042 §4.10: retention is a CORRECTNESS floor, not a cleanup nicety — a key
# must outlive every outbox row that can still replay it, else the replay turns
# into a new operation and double-applies. The Android outbox caps
# RetryableFailure at max_attempts=10 (with back-off) and GCs DONE rows at 7
# days, but a PENDING row on a long-offline device is bounded by neither — it
# replays whenever connectivity returns. 30 days comfortably covers realistic
# offline windows and exceeds the 7-day DONE GC. Beyond it, an extreme-tail
# replay degrades to the original false-409 (acceptable). A future slice that
# caps outbox unresolved-row age can tighten this to a derived bound; the GC
# sweep that deletes expired keys is deferred until keys are actually written.
DEFAULT_IDEMPOTENCY_RETENTION = timedelta(days=30)

# §4.4: an ``in_progress`` placeholder whose owner crashed before recording
# success would block the key's retry forever. Treat one older than this as
# abandoned and reclaimable.
DEFAULT_STALE_IN_PROGRESS = timedelta(minutes=10)


class IdempotencyOutcomeKind(StrEnum):
    PROCEED = "proceed"
    HIT = "hit"
    IN_PROGRESS = "in_progress"
    FINGERPRINT_MISMATCH = "fingerprint_mismatch"


@dataclass
class IdempotencyOutcome:
    kind: IdempotencyOutcomeKind
    row: ApiIdempotencyKey


def fingerprint_request(
    *,
    operation: str,
    target_id: str | None,
    body: Any,
    expected_row_version: int | None,
) -> str:
    """Canonical sha256 of (operation, target, body, expected_row_version).

    Same key + different fingerprint → ``idempotency_key_reused`` (§4.7). The
    ``expected_row_version`` is part of the fingerprint on purpose: a KeepMine
    that refreshes the token is a NEW intent and must rotate a NEW key (§4.8),
    so it should NOT collide with the original under the same fingerprint.

    ``body`` must be JSON-primitive with string keys (e.g. a Pydantic
    ``model_dump(mode="json")``) — ``default=str`` only rescues stray datetimes.
    Do NOT rely on the fingerprint distinguishing ``int`` vs ``str`` dict keys
    or custom ``__str__`` objects; pass already-canonical request data.
    """
    canonical = json.dumps(
        {
            "operation": operation,
            "target_id": target_id,
            "body": body,
            "expected_row_version": expected_row_version,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def claim_idempotency_key(
    db: Session,
    *,
    tenant_id: str,
    idempotency_key: str,
    operation: str,
    request_fingerprint: str,
    target_type: str | None = None,
    target_id: str | None = None,
    retention: timedelta = DEFAULT_IDEMPOTENCY_RETENTION,
    stale_in_progress_after: timedelta = DEFAULT_STALE_IN_PROGRESS,
) -> IdempotencyOutcome:
    """Atomically claim ``idempotency_key`` for ``tenant_id`` (ADR-0042 §4.4)."""
    now = now_utc()
    # Atomic claim: try to INSERT the in_progress placeholder inside a SAVEPOINT
    # so a unique-conflict rolls back only this insert (not the caller's outer
    # transaction). PostgreSQL auto-opens the enclosing transaction, so the
    # ``begin_nested()`` SAVEPOINT nests cleanly and a caller rollback undoes the
    # claim (ADR-0042 §4.9). Portable claim path — no ON CONFLICT DSL.
    try:
        with db.begin_nested():
            row = ApiIdempotencyKey(
                tenant_id=tenant_id,
                idempotency_key=idempotency_key,
                operation=operation,
                target_type=target_type,
                target_id=target_id,
                request_fingerprint=request_fingerprint,
                status=IDEMPOTENCY_STATUS_IN_PROGRESS,
                created_at=now,
                expires_at=now + retention,
            )
            db.add(row)
            db.flush()
        return IdempotencyOutcome(IdempotencyOutcomeKind.PROCEED, row)
    except IntegrityError:
        # Expected: another caller won the (tenant_id, idempotency_key) unique
        # race — re-read it below. A NON-conflict IntegrityError (e.g. a bad
        # tenant_id FK or the status CHECK) leaves no matching row, so re-raise
        # it rather than masking it as a missing-row 500.
        existing = db.execute(
            select(ApiIdempotencyKey)
            .where(ApiIdempotencyKey.tenant_id == tenant_id)
            .where(ApiIdempotencyKey.idempotency_key == idempotency_key)
        ).scalar_one_or_none()
        if existing is None:
            raise

    if existing.status == IDEMPOTENCY_STATUS_SUCCEEDED:
        if existing.request_fingerprint != request_fingerprint:
            return IdempotencyOutcome(
                IdempotencyOutcomeKind.FINGERPRINT_MISMATCH, existing
            )
        return IdempotencyOutcome(IdempotencyOutcomeKind.HIT, existing)

    # status == in_progress. A DIFFERENT request reusing the same key is a reuse
    # (§4.7) regardless of staleness — reject it BEFORE any reclaim, exactly like
    # the succeeded branch, so a stale placeholder can never be silently
    # overwritten by (and re-attributed to) an unrelated request.
    if existing.request_fingerprint != request_fingerprint:
        return IdempotencyOutcome(IdempotencyOutcomeKind.FINGERPRINT_MISMATCH, existing)

    # Same request. Reclaim the slot if its owner went stale (crashed before
    # recording success); otherwise a concurrent same-key request is still in
    # flight. Staleness is checked Python-side via ensure_utc so it stays
    # dialect-safe (SQLite reads timestamps back naive). operation/target/
    # fingerprint already match (guarded above), so the reclaim only restarts
    # the clock. Residual race: two requests both finding the SAME stale
    # placeholder within the window could both reclaim and double-apply — an
    # extreme tail (a >stale_after-old crash plus concurrent retries) accepted
    # for now.
    age = now - ensure_utc(existing.created_at)
    if age > stale_in_progress_after:
        existing.created_at = now
        existing.expires_at = now + retention
        db.flush()
        return IdempotencyOutcome(IdempotencyOutcomeKind.PROCEED, existing)

    return IdempotencyOutcome(IdempotencyOutcomeKind.IN_PROGRESS, existing)


def mark_idempotency_succeeded(
    db: Session,
    row: ApiIdempotencyKey,
    *,
    resource_type: str | None = None,
    resource_id: str | None = None,
) -> None:
    """Flip a claimed ``in_progress`` row to ``succeeded`` (ADR-0042 §4.5).

    Caller invokes this AFTER the business mutation and BEFORE the shared
    ``db.commit()`` so the idempotency record and the mutation land atomically.
    """
    row.status = IDEMPOTENCY_STATUS_SUCCEEDED
    # §4.6: a HIT replay re-serialises canonical state from resource_type/
    # resource_id. Fall back to the claim's target_* (set at claim time) when a
    # caller omits them — for most mutations target == resource — so the locator
    # the HIT path depends on is never silently nulled out.
    row.resource_type = resource_type if resource_type is not None else row.target_type
    row.resource_id = resource_id if resource_id is not None else row.target_id
    row.completed_at = now_utc()
    db.flush()


def reject_idempotency_target_mismatch(
    db: Session,
    *,
    tenant_id: str,
    idempotency_key: str,
    operation: str,
    target_id: str,
    target_type: str,
) -> None:
    """Reject an existing key before route-local canonicalization reads.

    Most routes can build the full fingerprint without loading business state.
    Proposal confirm needs the proposal's amount to collapse explicit-full and
    omitted-full bodies into one fingerprint. This preflight preserves the
    shared claim helper's target-mismatch behavior before that lookup runs.
    """
    existing = db.execute(
        select(ApiIdempotencyKey)
        .where(ApiIdempotencyKey.tenant_id == tenant_id)
        .where(ApiIdempotencyKey.idempotency_key == idempotency_key)
        .limit(1)
    ).scalar_one_or_none()
    if existing is None:
        return
    if (
        existing.operation != operation
        or existing.target_type != target_type
        or existing.target_id != target_id
    ):
        raise AppError("idempotency_key_reused", status_code=422)


def claim_idempotent_request(
    db: Session,
    *,
    idempotency_key: str | None,
    tenant_id: str,
    operation: str,
    target_id: str,
    body: Any,
    expected_row_version: int | None,
    target_type: str = "expense",
) -> ApiIdempotencyKey | None:
    """Route-layer ADR-0042 claim-before-OCC handshake (§4.4) — the shared front
    door every outbox-routed mutate route uses.

    Returns the claimed ``in_progress`` row to PROCEED with: the caller runs the
    mutation with ``commit=False``, then calls :func:`mark_idempotency_succeeded`
    and a SINGLE ``db.commit()`` so the success record and the mutation land
    atomically (§4.5). Returns ``None`` on a HIT — the key already succeeded, so
    the caller re-serialises the resource's current canonical state instead of
    re-running the mutation (§4.6, kills the committed-but-unseen false-409).

    Raises :class:`AppError` for the three contract-violation outcomes so the
    route body stays a thin ``if claim is None`` branch:

    * no key            → 422 ``idempotency_key_required``
    * concurrent in-flight (same key) → 409 ``idempotency_key_in_progress``
    * same key, different request (fingerprint mismatch) → 422
      ``idempotency_key_reused``

    ``body`` must be JSON-canonical (a Pydantic ``model_dump(mode="json",
    exclude_unset=True, exclude={"expected_row_version"})``); for a token-only
    request it is ``{}`` and ``operation`` + ``target_id`` keep the fingerprint
    distinct per (op, target, token).
    """
    if not idempotency_key:
        raise AppError("idempotency_key_required", status_code=422)
    fingerprint = fingerprint_request(
        operation=operation,
        target_id=target_id,
        body=body,
        expected_row_version=expected_row_version,
    )
    outcome = claim_idempotency_key(
        db,
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
        operation=operation,
        request_fingerprint=fingerprint,
        target_type=target_type,
        target_id=target_id,
    )
    if outcome.kind is IdempotencyOutcomeKind.HIT:
        return None
    if outcome.kind is IdempotencyOutcomeKind.IN_PROGRESS:
        raise AppError("idempotency_key_in_progress", status_code=409)
    if outcome.kind is IdempotencyOutcomeKind.FINGERPRINT_MISMATCH:
        raise AppError("idempotency_key_reused", status_code=422)
    return outcome.row
