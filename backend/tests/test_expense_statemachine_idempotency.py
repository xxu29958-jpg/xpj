"""ADR-0042 Slice D-1: request-idempotency for the expense state-machine
mutations (confirm / reject / mark-not-duplicate / retry-ocr / acknowledge).

Uniform contract: every outbox-routed state op claims an ``Idempotency-Key``
before its OCC claim, mirroring Slice B's PATCH. Two flavours of op:

* ``mark_not_duplicate`` / ``retry_ocr`` / ``acknowledge`` are NOT terminal-
  idempotent — a committed-but-unseen replay would hit their OCC claim with a
  now-stale ``expected_row_version`` and false-409. The key is what makes the
  replay re-serialise canonical state instead (the meaningful fix, exercised on
  ``mark_not_duplicate`` below).
* ``confirm`` / ``reject`` are ALSO terminal-idempotent at the service layer
  (``if status == confirmed: return`` runs before the token check), so their
  replay was already 200 without a key. They carry the key anyway for a uniform
  "every outbox mutate op requires a key" contract — redundant but harmless
  (the no-op PROCEED still records the key, verified below).

The per-op claim plumbing is the SAME shared ``claim_idempotent_request``
helper Slice B's unit tests already cover; these route tests pin the wiring +
the false-409 fix, not the helper internals.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from api_contract_helpers import confirm_expense_api, upload_png
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import ApiIdempotencyKey, Expense
from app.services.idempotency import (
    IDEMPOTENCY_STATUS_IN_PROGRESS,
    IDEMPOTENCY_STATUS_SUCCEEDED,
    fingerprint_request,
)
from app.services.time_service import now_utc

if TYPE_CHECKING:
    from tests._infra.identity import TestIdentity


def _row_version(client: TestClient, expense_id: int, *, identity: TestIdentity) -> int:
    resp = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["row_version"]


def _seed_suspected_duplicate(client: TestClient, *, identity: TestIdentity) -> int:
    """Upload + flag the row as a suspected duplicate so mark-not-duplicate has
    something to clear (mirrors the state-machine OCC test's seeding)."""
    expense_id = upload_png(client, identity=identity)
    with SessionLocal() as db:
        row = db.scalar(select(Expense).where(Expense.id == expense_id))
        assert row is not None
        row.duplicate_status = "suspected"
        row.duplicate_of_id = expense_id
        row.duplicate_reason = "test"
        db.commit()
    return expense_id


_STATE_OPS = [
    "confirm",
    "reject",
    "mark-not-duplicate",
    "ocr/retry",
    "items/acknowledge-mismatch",
]


@pytest.mark.parametrize("op", _STATE_OPS)
def test_state_op_requires_idempotency_key(
    client: TestClient, identity: TestIdentity, op: str
) -> None:
    """Every outbox-routed state op rejects a keyless request with 422 — the
    missing-key guard runs before the service, so a valid body still 422s."""
    expense_id = upload_png(client, identity=identity)
    v0 = _row_version(client, expense_id, identity=identity)
    resp = client.post(
        f"/api/expenses/{expense_id}/{op}",
        headers=identity.app_headers,  # no Idempotency-Key
        json={"expected_row_version": v0},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"] == "idempotency_key_required"


def test_mark_not_duplicate_replay_same_key_returns_canonical_not_409(
    client: TestClient, identity: TestIdentity
) -> None:
    """Committed-but-unseen: the SAME key + SAME now-stale token returns the
    canonical (already-cleared) row, never the false-409 the OCC claim would
    otherwise raise (mark-not-duplicate is NOT terminal-idempotent)."""
    expense_id = _seed_suspected_duplicate(client, identity=identity)
    v0 = _row_version(client, expense_id, identity=identity)
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}
    body = {"expected_row_version": v0}

    first = client.post(
        f"/api/expenses/{expense_id}/mark-not-duplicate", headers=headers, json=body
    )
    assert first.status_code == 200, first.text
    assert first.json()["duplicate_status"] == "none"
    v1 = first.json()["row_version"]
    assert v1 != v0

    replay = client.post(
        f"/api/expenses/{expense_id}/mark-not-duplicate", headers=headers, json=body
    )
    assert replay.status_code == 200, replay.text  # NOT 409
    assert replay.json()["duplicate_status"] == "none"
    assert replay.json()["row_version"] == v1  # canonical, not re-applied


def test_mark_not_duplicate_stale_token_with_different_key_still_409s(
    client: TestClient, identity: TestIdentity
) -> None:
    """Negative control: a DIFFERENT key with the same now-stale token is a
    genuine concurrent writer → OCC 409 stays intact (idempotency didn't
    weaken OCC)."""
    expense_id = _seed_suspected_duplicate(client, identity=identity)
    v0 = _row_version(client, expense_id, identity=identity)
    body = {"expected_row_version": v0}

    first = client.post(
        f"/api/expenses/{expense_id}/mark-not-duplicate",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json=body,
    )
    assert first.status_code == 200, first.text

    stale = client.post(
        f"/api/expenses/{expense_id}/mark-not-duplicate",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json=body,
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"] == "state_conflict"


def test_mark_not_duplicate_in_progress_returns_409(
    client: TestClient, identity: TestIdentity
) -> None:
    """A fresh in_progress placeholder (same key + fingerprint) blocks a second
    same-key request → 409 idempotency_key_in_progress."""
    expense_id = _seed_suspected_duplicate(client, identity=identity)
    v0 = _row_version(client, expense_id, identity=identity)
    key = str(uuid4())
    fingerprint = fingerprint_request(
        operation="mark_not_duplicate",
        target_id=str(expense_id),
        body={},  # token-only request → empty body after exclude
        expected_row_version=v0,
    )
    with SessionLocal() as db:
        db.add(
            ApiIdempotencyKey(
                tenant_id="owner",
                idempotency_key=key,
                operation="mark_not_duplicate",
                target_type="expense",
                target_id=str(expense_id),
                request_fingerprint=fingerprint,
                status=IDEMPOTENCY_STATUS_IN_PROGRESS,
                created_at=now_utc(),
                expires_at=now_utc() + timedelta(days=1),
            )
        )
        db.commit()

    resp = client.post(
        f"/api/expenses/{expense_id}/mark-not-duplicate",
        headers={**identity.app_headers, "Idempotency-Key": key},
        json={"expected_row_version": v0},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"] == "idempotency_key_in_progress"


def test_mark_not_duplicate_same_key_different_token_is_reused_422(
    client: TestClient, identity: TestIdentity
) -> None:
    """§4.7: same key, different request (a different expected_row_version, the
    only varying field for a token-only op) → 422 idempotency_key_reused."""
    expense_id = _seed_suspected_duplicate(client, identity=identity)
    v0 = _row_version(client, expense_id, identity=identity)
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}

    first = client.post(
        f"/api/expenses/{expense_id}/mark-not-duplicate",
        headers=headers,
        json={"expected_row_version": v0},
    )
    assert first.status_code == 200, first.text

    reused = client.post(
        f"/api/expenses/{expense_id}/mark-not-duplicate",
        headers=headers,
        json={"expected_row_version": v0 + 7},  # different token → different intent
    )
    assert reused.status_code == 422, reused.text
    assert reused.json()["error"] == "idempotency_key_reused"


def test_confirm_proceed_records_key_even_on_terminal_noop(
    client: TestClient, identity: TestIdentity
) -> None:
    """confirm is terminal-idempotent, but the uniform key contract must still
    record a fresh key on an already-confirmed (no-op PROCEED) row — otherwise
    the key would leak as in_progress. A later replay of that key HITs."""
    expense_id = upload_png(client, identity=identity)
    # Make it confirm-able then confirm once (its own minted key).
    snap = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers).json()
    client.patch(
        f"/api/expenses/{expense_id}",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"amount_cents": 1234, "expected_row_version": snap["row_version"]},
    )
    assert confirm_expense_api(client, expense_id, headers=identity.app_headers).status_code == 200

    # A fresh-key confirm on the already-confirmed row → 200 (terminal no-op),
    # and the key is recorded succeeded (not left in_progress).
    key = str(uuid4())
    v_now = _row_version(client, expense_id, identity=identity)
    resp = client.post(
        f"/api/expenses/{expense_id}/confirm",
        headers={**identity.app_headers, "Idempotency-Key": key},
        json={"expected_row_version": v_now},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "confirmed"
    with SessionLocal() as db:
        row = db.execute(
            select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key)
        ).scalar_one()
    assert row.status == IDEMPOTENCY_STATUS_SUCCEEDED
