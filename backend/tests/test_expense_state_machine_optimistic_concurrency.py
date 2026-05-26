"""ADR-0038 PR-2b contract tests for the expense state-machine endpoints.

Covers ``POST /api/expenses/{id}/confirm``, ``/reject``, and
``/mark-not-duplicate``. Each must:

* require ``expected_updated_at`` (Pydantic 422 if missing);
* succeed with a fresh token;
* return ``409 state_conflict`` if the row's ``updated_at`` already
  moved past the client's snapshot;
* preserve idempotency on terminal status (``confirmed`` / ``rejected``);
* return 404 for non-existent rows.

The bottom service-level tests cover the read/read/write/write race
the HTTP-level replay can't easily reproduce: two SQLAlchemy sessions
both read T1, A commits to T2, B's atomic ``UPDATE WHERE updated_at =
T1`` predicate is the DB-layer guard.
"""

from __future__ import annotations

import pytest
from api_contract_helpers import (
    confirm_expense_api,
    mark_not_duplicate_api,
    patch_expense,
    reject_expense_api,
)
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.models import Expense
from app.services.expense_service import (
    confirm_expense,
    mark_expense_not_duplicate,
    reject_expense,
)
from tests._infra.assets import PNG_BYTES


def _create_pending(client: TestClient, *, identity) -> int:
    resp = client.post(
        identity.upload_url_path,
        headers={**identity.upload_headers, "Content-Type": "image/png"},
        content=PNG_BYTES,
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


def _seed_ready(client: TestClient, *, identity) -> int:
    """Upload + patch amount so the row is confirm-able (amount_cents set)."""
    expense_id = _create_pending(client, identity=identity)
    resp = patch_expense(
        client,
        expense_id,
        headers=identity.app_headers,
        fields={"amount_cents": 1234, "merchant": "Test Cafe"},
    )
    assert resp.status_code == 200, resp.text
    return expense_id


def _snapshot_updated_at(
    client: TestClient, expense_id: int, *, identity
) -> str:
    resp = client.get(
        f"/api/expenses/{expense_id}", headers=identity.app_headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["updated_at"]


# ---------------------------------------------------------------------------
# confirm


def test_confirm_with_fresh_updated_at_succeeds(
    client: TestClient, *, identity
) -> None:
    expense_id = _seed_ready(client, identity=identity)
    resp = confirm_expense_api(client, expense_id, headers=identity.app_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "confirmed"


def test_confirm_with_stale_updated_at_returns_409(
    client: TestClient, *, identity
) -> None:
    expense_id = _seed_ready(client, identity=identity)
    stale_token = _snapshot_updated_at(client, expense_id, identity=identity)
    # Bump updated_at via PATCH so the original snapshot is now stale.
    patched = patch_expense(
        client,
        expense_id,
        headers=identity.app_headers,
        fields={"merchant": "Renamed"},
    )
    assert patched.status_code == 200, patched.text
    stale = client.post(
        f"/api/expenses/{expense_id}/confirm",
        headers=identity.app_headers,
        json={"expected_updated_at": stale_token},
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"] == "state_conflict"


def test_confirm_without_expected_updated_at_returns_422(
    client: TestClient, *, identity
) -> None:
    expense_id = _seed_ready(client, identity=identity)
    resp = client.post(
        f"/api/expenses/{expense_id}/confirm",
        headers=identity.app_headers,
        json={},
    )
    assert resp.status_code == 422, resp.text


def test_confirm_already_confirmed_is_idempotent(
    client: TestClient, *, identity
) -> None:
    """Terminal status idempotency: a second confirm with any token
    returns 200 (server treats ``confirmed`` as a fixed point)."""
    expense_id = _seed_ready(client, identity=identity)
    first = confirm_expense_api(client, expense_id, headers=identity.app_headers)
    assert first.status_code == 200
    # Replay with a stale token after confirmation — still 200 because
    # the row is already terminal.
    replay = client.post(
        f"/api/expenses/{expense_id}/confirm",
        headers=identity.app_headers,
        json={"expected_updated_at": "2026-01-01T00:00:00Z"},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["status"] == "confirmed"


def test_confirm_unknown_expense_returns_404(
    client: TestClient, *, identity
) -> None:
    resp = client.post(
        "/api/expenses/9999999/confirm",
        headers=identity.app_headers,
        json={"expected_updated_at": "2026-05-04T00:00:00Z"},
    )
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# reject


def test_reject_with_fresh_updated_at_succeeds(
    client: TestClient, *, identity
) -> None:
    expense_id = _create_pending(client, identity=identity)
    resp = reject_expense_api(client, expense_id, headers=identity.app_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "rejected"


def test_reject_with_stale_updated_at_returns_409(
    client: TestClient, *, identity
) -> None:
    expense_id = _create_pending(client, identity=identity)
    stale_token = _snapshot_updated_at(client, expense_id, identity=identity)
    patched = patch_expense(
        client,
        expense_id,
        headers=identity.app_headers,
        fields={"merchant": "Renamed"},
    )
    assert patched.status_code == 200, patched.text
    stale = client.post(
        f"/api/expenses/{expense_id}/reject",
        headers=identity.app_headers,
        json={"expected_updated_at": stale_token},
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"] == "state_conflict"


def test_reject_without_expected_updated_at_returns_422(
    client: TestClient, *, identity
) -> None:
    expense_id = _create_pending(client, identity=identity)
    resp = client.post(
        f"/api/expenses/{expense_id}/reject",
        headers=identity.app_headers,
        json={},
    )
    assert resp.status_code == 422, resp.text


def test_reject_already_rejected_is_idempotent(
    client: TestClient, *, identity
) -> None:
    expense_id = _create_pending(client, identity=identity)
    first = reject_expense_api(client, expense_id, headers=identity.app_headers)
    assert first.status_code == 200
    replay = client.post(
        f"/api/expenses/{expense_id}/reject",
        headers=identity.app_headers,
        json={"expected_updated_at": "2026-01-01T00:00:00Z"},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["status"] == "rejected"


# ---------------------------------------------------------------------------
# mark-not-duplicate


def test_mark_not_duplicate_with_fresh_updated_at_succeeds(
    client: TestClient, *, identity
) -> None:
    expense_id = _create_pending(client, identity=identity)
    # Mark the row as a suspected duplicate directly so mark-not-duplicate
    # has something to clear (server-side flag manipulation; UI normally
    # flags via OCR detection).
    with SessionLocal() as db:
        row = db.scalar(select(Expense).where(Expense.id == expense_id))
        assert row is not None
        row.duplicate_status = "suspected"
        row.duplicate_of_id = expense_id  # self-ref ok for unit purposes
        row.duplicate_reason = "test"
        db.commit()

    resp = mark_not_duplicate_api(
        client, expense_id, headers=identity.app_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["duplicate_status"] == "none"


def test_mark_not_duplicate_with_stale_updated_at_returns_409(
    client: TestClient, *, identity
) -> None:
    expense_id = _create_pending(client, identity=identity)
    stale_token = _snapshot_updated_at(client, expense_id, identity=identity)
    patched = patch_expense(
        client,
        expense_id,
        headers=identity.app_headers,
        fields={"merchant": "Renamed"},
    )
    assert patched.status_code == 200, patched.text
    stale = client.post(
        f"/api/expenses/{expense_id}/mark-not-duplicate",
        headers=identity.app_headers,
        json={"expected_updated_at": stale_token},
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"] == "state_conflict"


def test_mark_not_duplicate_without_expected_updated_at_returns_422(
    client: TestClient, *, identity
) -> None:
    expense_id = _create_pending(client, identity=identity)
    resp = client.post(
        f"/api/expenses/{expense_id}/mark-not-duplicate",
        headers=identity.app_headers,
        json={},
    )
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# Service-level read/read/write/write race — these are the critical
# tests proving the DB-level predicate is what guards us, not a
# Python-side comparison (which two sessions can race past).


def test_two_sessions_seeing_same_updated_at_only_first_confirm_wins(
    client: TestClient, *, identity
) -> None:
    expense_id = _seed_ready(client, identity=identity)
    tenant_id = "owner"

    session_a = SessionLocal()
    session_b = SessionLocal()
    try:
        row_a = session_a.scalar(select(Expense).where(Expense.id == expense_id))
        row_b = session_b.scalar(select(Expense).where(Expense.id == expense_id))
        assert row_a is not None and row_b is not None
        assert row_a.updated_at == row_b.updated_at
        shared_version = row_a.updated_at

        # Writer A patches then commits (bumps updated_at to T2).
        # We use update_expense semantics via a direct UPDATE to keep
        # the test focused on the state-machine claim, not the full
        # PATCH path.
        from datetime import timedelta

        from sqlalchemy import update

        new_t = shared_version + timedelta(seconds=1)
        session_a.execute(
            update(Expense)
            .where(Expense.id == expense_id)
            .values(updated_at=new_t)
        )
        session_a.commit()

        # Writer B replays the stale shared_version → claim rejects.
        with pytest.raises(AppError) as exc_info:
            confirm_expense(
                session_b,
                expense_id,
                tenant_id,
                expected_updated_at=shared_version,
            )
        assert exc_info.value.error == "state_conflict"
        assert exc_info.value.status_code == 409
    finally:
        session_a.close()
        session_b.close()


def test_two_sessions_concurrent_reject_then_confirm_resolves_to_404(
    client: TestClient, *, identity
) -> None:
    """Writer A rejects (terminal), B's confirm with pre-reject token →
    404 because the row is no longer in pending."""
    expense_id = _seed_ready(client, identity=identity)
    tenant_id = "owner"

    session_a = SessionLocal()
    session_b = SessionLocal()
    try:
        row_a = session_a.scalar(select(Expense).where(Expense.id == expense_id))
        row_b = session_b.scalar(select(Expense).where(Expense.id == expense_id))
        assert row_a is not None and row_b is not None
        shared_version = row_a.updated_at

        reject_expense(
            session_a,
            expense_id,
            tenant_id,
            expected_updated_at=shared_version,
        )

        with pytest.raises(AppError) as exc_info:
            confirm_expense(
                session_b,
                expense_id,
                tenant_id,
                expected_updated_at=shared_version,
            )
        assert exc_info.value.error == "expense_not_found"
        assert exc_info.value.status_code == 404
    finally:
        session_a.close()
        session_b.close()


def test_two_sessions_mark_not_duplicate_race(
    client: TestClient, *, identity
) -> None:
    """Both sessions see same suspected-duplicate row; A clears first, B's
    replay on the pre-clear token → 409 from atomic UPDATE WHERE."""
    expense_id = _create_pending(client, identity=identity)
    with SessionLocal() as setup_db:
        row = setup_db.scalar(select(Expense).where(Expense.id == expense_id))
        assert row is not None
        row.duplicate_status = "suspected"
        row.duplicate_of_id = expense_id
        row.duplicate_reason = "race"
        setup_db.commit()

    tenant_id = "owner"
    session_a = SessionLocal()
    session_b = SessionLocal()
    try:
        row_a = session_a.scalar(select(Expense).where(Expense.id == expense_id))
        row_b = session_b.scalar(select(Expense).where(Expense.id == expense_id))
        assert row_a is not None and row_b is not None
        shared_version = row_a.updated_at

        mark_expense_not_duplicate(
            session_a,
            expense_id,
            tenant_id,
            expected_updated_at=shared_version,
        )

        with pytest.raises(AppError) as exc_info:
            mark_expense_not_duplicate(
                session_b,
                expense_id,
                tenant_id,
                expected_updated_at=shared_version,
            )
        assert exc_info.value.error == "state_conflict"
        assert exc_info.value.status_code == 409
    finally:
        session_a.close()
        session_b.close()
