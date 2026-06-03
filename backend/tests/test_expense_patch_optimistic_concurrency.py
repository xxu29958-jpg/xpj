"""ADR-0038 contract tests for expense PATCH.

PR-2a 在真实业务路径上落实乐观锁：``PATCH /api/expenses/{id}`` 必须
携带 ``expected_row_version``，stale snapshot 落到 ``409 state_conflict``；
缺字段（提交未带）则在 Pydantic 校验层 422 fail-fast。

底部的 service-level test 通过两个 SQLAlchemy session 走 read/read/
write/write 半场：两边都读到 T1，A 先提交到 T2，B 再用 T1 触发原子
``UPDATE WHERE updated_at = T1`` —— DB 层 rowcount=0 直接拒绝（pre-fix
的 Python-side check 这里会两个都过）。
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.models import Expense
from app.schemas import ExpenseUpdateRequest
from app.services.expense_service import update_expense
from tests._infra.assets import PNG_BYTES


def _create_pending(client: TestClient, *, identity) -> int:
    """Upload + return an expense_id so PATCH-able rows exist."""
    resp = client.post(
        identity.upload_url_path,
        headers={**identity.upload_headers, "Content-Type": "image/png"},
        content=PNG_BYTES,
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


def _snapshot(client: TestClient, expense_id: int, *, identity) -> dict:
    resp = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# HTTP contract


def test_patch_expense_with_fresh_updated_at_succeeds(
    client: TestClient, *, identity
) -> None:
    expense_id = _create_pending(client, identity=identity)
    snapshot = _snapshot(client, expense_id, identity=identity)
    resp = client.patch(
        f"/api/expenses/{expense_id}",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "merchant": "Fresh Cafe",
            "amount_cents": 1234,
            "expected_row_version": snapshot["row_version"],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["merchant"] == "Fresh Cafe"
    assert body["amount_cents"] == 1234
    assert body["updated_at"] != snapshot["updated_at"]


def test_patch_expense_with_stale_updated_at_returns_409(
    client: TestClient, *, identity
) -> None:
    expense_id = _create_pending(client, identity=identity)
    snapshot = _snapshot(client, expense_id, identity=identity)
    # First PATCH succeeds and bumps updated_at. Distinct Idempotency-Key per
    # intent: "First" and "Second" are different requests, so the second must
    # reach the OCC layer (→ 409) rather than HIT the first's idempotency record.
    first = client.patch(
        f"/api/expenses/{expense_id}",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "merchant": "First",
            "expected_row_version": snapshot["row_version"],
        },
    )
    assert first.status_code == 200, first.text
    # Second PATCH replays the original updated_at — now stale.
    stale = client.patch(
        f"/api/expenses/{expense_id}",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "merchant": "Second",
            "expected_row_version": snapshot["row_version"],
        },
    )
    assert stale.status_code == 409, stale.text
    body = stale.json()
    assert body["error"] == "state_conflict"
    assert body["message"]


def test_patch_expense_without_expected_row_version_returns_422(
    client: TestClient, *, identity
) -> None:
    expense_id = _create_pending(client, identity=identity)
    # Header present so the 422 is unambiguously the missing OCC token (body
    # validation), not the ADR-0042 missing-key guard.
    resp = client.patch(
        f"/api/expenses/{expense_id}",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"merchant": "Missing Token"},
    )
    assert resp.status_code == 422, resp.text


def test_patch_unknown_expense_returns_404(
    client: TestClient, *, identity
) -> None:
    """Even with a syntactically-valid token, a non-existent id must 404."""
    resp = client.patch(
        "/api/expenses/9999999",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "merchant": "Ghost",
            "expected_row_version": 999999,
        },
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"] == "expense_not_found"


# ---------------------------------------------------------------------------
# Atomic write/write race — exercise the claim-then-apply path with two
# SessionLocal handles so the test does not depend on threaded HTTP
# clients. Pre-PR-2a a Python-side ``expense.updated_at != expected``
# check would let both writers pass; the atomic ``UPDATE WHERE
# updated_at = expected`` predicate rejects the second one here.


def test_two_sessions_seeing_same_updated_at_only_first_writer_wins(
    client: TestClient, *, identity
) -> None:
    expense_id = _create_pending(client, identity=identity)
    tenant_id = "owner"

    session_a = SessionLocal()
    session_b = SessionLocal()
    try:
        row_a = session_a.scalar(select(Expense).where(Expense.id == expense_id))
        row_b = session_b.scalar(select(Expense).where(Expense.id == expense_id))
        assert row_a is not None and row_b is not None
        # Both sessions read the same version.
        assert row_a.row_version == row_b.row_version
        shared_version = row_a.row_version

        # Writer A commits first — succeeds.
        update_expense(
            session_a,
            expense_id,
            tenant_id,
            ExpenseUpdateRequest(
                expected_row_version=shared_version,
                merchant="Writer A",
            ),
        )

        # Writer B replays the stale shared_version. Pre-fix this
        # would silently overwrite A's change; post-fix the UPDATE
        # WHERE predicate finds rowcount=0 and we surface
        # state_conflict 409.
        with pytest.raises(AppError) as exc_info:
            update_expense(
                session_b,
                expense_id,
                tenant_id,
                ExpenseUpdateRequest(
                    expected_row_version=shared_version,
                    merchant="Writer B",
                ),
            )
        assert exc_info.value.error == "state_conflict"
        assert exc_info.value.status_code == 409
    finally:
        session_a.close()
        session_b.close()


def test_two_sessions_concurrent_reject_then_patch_resolves_to_404(
    client: TestClient, *, identity
) -> None:
    """Variant: writer A rejects (moves row to ``rejected`` — not in
    ``EDITABLE_STATUSES``); writer B tries to PATCH with the
    pre-reject expected_row_version. The atomic UPDATE finds no row
    in editable status (rowcount=0); the 404/409 disambiguation
    surfaces ``expense_not_found`` because the row is no longer
    editable.
    """
    expense_id = _create_pending(client, identity=identity)
    tenant_id = "owner"

    session_a = SessionLocal()
    session_b = SessionLocal()
    try:
        row_a = session_a.scalar(select(Expense).where(Expense.id == expense_id))
        row_b = session_b.scalar(select(Expense).where(Expense.id == expense_id))
        assert row_a is not None and row_b is not None
        shared_version = row_a.row_version

        # Writer A moves the row out of EDITABLE_STATUSES.
        from app.services.expense_service import reject_expense

        reject_expense(
            session_a,
            expense_id,
            tenant_id,
            expected_row_version=shared_version,
        )

        with pytest.raises(AppError) as exc_info:
            update_expense(
                session_b,
                expense_id,
                tenant_id,
                ExpenseUpdateRequest(
                    expected_row_version=shared_version,
                    merchant="Late Edit",
                ),
            )
        assert exc_info.value.error == "expense_not_found"
        assert exc_info.value.status_code == 404
    finally:
        session_a.close()
        session_b.close()
