"""ADR-0042 Slice B: idempotent ``PATCH /api/expenses/{id}`` route tests.

Slice A wired the ``api_idempotency_keys`` table + helper but left it
unconsumed. Slice B is the first HTTP surface to claim a key BEFORE the OCC
``row_version`` claim (§4.4). The four behaviours exercised here:

* **committed-but-unseen** — the scenario the whole mechanism exists for. A
  direct PATCH commits server-side but its response is lost on the wire; the
  Android outbox replays with the SAME key + the SAME (now-stale)
  ``expected_row_version``. Without idempotency the OCC predicate false-409s
  (the row moved on). With it, the replay HITs and re-serialises the canonical
  current row (§4.6) → 200, not 409. (Contrast the sibling
  ``test_patch_expense_with_stale_updated_at_returns_409``: a DIFFERENT key with
  a stale token still 409s — OCC is intact for genuine concurrent writers.)
* **header-required** — outbox-routed mutate面 must carry ``Idempotency-Key``.
* **fingerprint-mismatch** — same key, different request body → 422 reuse.
* **in-progress** — same key held by a concurrent (not-yet-succeeded) request
  → 409.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import ApiIdempotencyKey
from app.schemas import ExpenseUpdateRequest
from app.services.idempotency import (
    IDEMPOTENCY_STATUS_IN_PROGRESS,
    fingerprint_request,
)
from app.services.time_service import now_utc
from tests.api_contract_helpers import upload_png

if TYPE_CHECKING:
    # Runtime import would make pytest try to collect the ``TestIdentity``
    # dataclass as a test class (Test* prefix) — keep it type-only.
    from tests._infra.identity import TestIdentity


def _snapshot_row_version(client: TestClient, expense_id: int, *, identity: TestIdentity) -> int:
    resp = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["row_version"]


def test_patch_replay_same_key_returns_canonical_not_409(
    client: TestClient, identity: TestIdentity
) -> None:
    """Committed-but-unseen: replaying the SAME key + SAME stale token returns
    the canonical row (200), never the false-409 OCC would otherwise raise."""
    expense_id = upload_png(client, identity=identity)
    v0 = _snapshot_row_version(client, expense_id, identity=identity)

    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}
    body = {"merchant": "Replay Cafe", "expected_row_version": v0}

    first = client.patch(f"/api/expenses/{expense_id}", headers=headers, json=body)
    assert first.status_code == 200, first.text
    assert first.json()["merchant"] == "Replay Cafe"
    v1 = first.json()["row_version"]
    assert v1 != v0, "the first PATCH must bump row_version"

    # The outbox replays with the IDENTICAL key and the IDENTICAL (now-stale)
    # expected_row_version it originally enqueued. The key HITs → canonical row.
    replay = client.patch(f"/api/expenses/{expense_id}", headers=headers, json=body)
    assert replay.status_code == 200, replay.text  # NOT 409
    assert replay.json()["merchant"] == "Replay Cafe"
    assert replay.json()["row_version"] == v1, (
        "a HIT re-serialises canonical state; it must not re-apply / re-bump"
    )


def test_patch_missing_idempotency_key_returns_422(
    client: TestClient, identity: TestIdentity
) -> None:
    """Outbox-routed mutate面 MUST carry the key — absent → 422 (body is
    otherwise valid, so this is unambiguously the missing-key guard)."""
    expense_id = upload_png(client, identity=identity)
    v0 = _snapshot_row_version(client, expense_id, identity=identity)

    resp = client.patch(
        f"/api/expenses/{expense_id}",
        headers=identity.app_headers,  # no Idempotency-Key
        json={"merchant": "No Key", "expected_row_version": v0},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"] == "idempotency_key_required"


def test_patch_same_key_different_body_is_reuse_422(
    client: TestClient, identity: TestIdentity
) -> None:
    """§4.7: same key, different request → ``idempotency_key_reused`` (422),
    caught at the claim BEFORE the OCC layer."""
    expense_id = upload_png(client, identity=identity)
    v0 = _snapshot_row_version(client, expense_id, identity=identity)

    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}

    first = client.patch(
        f"/api/expenses/{expense_id}",
        headers=headers,
        json={"merchant": "Original", "expected_row_version": v0},
    )
    assert first.status_code == 200, first.text

    # Same key, different body (a genuinely different intent) → reuse, not HIT.
    reused = client.patch(
        f"/api/expenses/{expense_id}",
        headers=headers,
        json={"merchant": "Different", "expected_row_version": v0},
    )
    assert reused.status_code == 422, reused.text
    assert reused.json()["error"] == "idempotency_key_reused"


def test_patch_same_key_in_progress_returns_409(
    client: TestClient, identity: TestIdentity
) -> None:
    """§4.4: a fresh in_progress placeholder for the same key + same fingerprint
    (a concurrent request that claimed but hasn't recorded success) blocks a
    second same-key request → 409 ``idempotency_key_in_progress``."""
    expense_id = upload_png(client, identity=identity)
    v0 = _snapshot_row_version(client, expense_id, identity=identity)

    key = str(uuid4())
    # Build the fingerprint the route will compute, so the placeholder matches
    # (a mismatched fingerprint would surface as reuse/422 instead of 409).
    payload = ExpenseUpdateRequest(merchant="Inflight", expected_row_version=v0)
    fingerprint = fingerprint_request(
        operation="patch_expense",
        target_id=str(expense_id),
        body=payload.model_dump(
            mode="json", exclude_unset=True, exclude={"expected_row_version"}
        ),
        expected_row_version=v0,
    )
    # Insert a FRESH (non-stale) in_progress claim out-of-band, standing in for a
    # concurrent request still mid-flight.
    with SessionLocal() as db:
        db.add(
            ApiIdempotencyKey(
                tenant_id="owner",
                idempotency_key=key,
                operation="patch_expense",
                target_type="expense",
                target_id=str(expense_id),
                request_fingerprint=fingerprint,
                status=IDEMPOTENCY_STATUS_IN_PROGRESS,
                created_at=now_utc(),
                expires_at=now_utc() + timedelta(days=1),
            )
        )
        db.commit()

    resp = client.patch(
        f"/api/expenses/{expense_id}",
        headers={**identity.app_headers, "Idempotency-Key": key},
        json={"merchant": "Inflight", "expected_row_version": v0},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"] == "idempotency_key_in_progress"


def test_patch_occ_conflict_leaves_no_idempotency_row_and_key_is_reclaimable(
    client: TestClient, identity: TestIdentity
) -> None:
    """§4.9 + the invariant Android's same-key KeepMine replay relies on: a PATCH
    that fails the OCC check (409) must leave NO idempotency row for its key — the
    claim is rolled back together with the aborted mutation — so the key stays
    reclaimable (a corrected retry PROCEEDs, it doesn't false-mismatch)."""
    expense_id = upload_png(client, identity=identity)
    v0 = _snapshot_row_version(client, expense_id, identity=identity)

    # A different request bumps the row, making v0 stale.
    bumped = client.patch(
        f"/api/expenses/{expense_id}",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"merchant": "Bumped", "expected_row_version": v0},
    )
    assert bumped.status_code == 200, bumped.text
    v1 = bumped.json()["row_version"]

    # PATCH with key K + the now-stale v0 → OCC 409.
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}
    conflict = client.patch(
        f"/api/expenses/{expense_id}",
        headers=headers,
        json={"merchant": "Mine", "expected_row_version": v0},
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["error"] == "state_conflict"

    # The claim was rolled back with the aborted mutation: no row for key K.
    with SessionLocal() as db:
        rows = db.execute(
            select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key)
        ).scalars().all()
    assert rows == [], "an OCC-409 must leave no idempotency row (§4.9 reclaimable)"

    # Reclaimable: reusing key K with the corrected token PROCEEDs (not a spurious
    # idempotency_key_reused), because no prior K row survived the conflict.
    retry = client.patch(
        f"/api/expenses/{expense_id}",
        headers=headers,
        json={"merchant": "Mine", "expected_row_version": v1},
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["merchant"] == "Mine"
