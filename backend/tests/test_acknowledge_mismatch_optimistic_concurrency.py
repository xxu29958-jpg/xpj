"""ADR-0038 PR-2e contract tests for
``POST /api/expenses/{id}/items/acknowledge-mismatch``.

Previously the route accepted an empty body and the service did a
read-then-write that silently flipped ``items_sum_status`` from
``mismatch_known`` to ``mismatch_acknowledged``. With the token a stale
"原小票如此" click against a row whose amount/items a peer just edited
returns 409 ``state_conflict`` instead of writing an out-of-date ack.
"""

from __future__ import annotations

import pytest
from api_contract_helpers import (
    acknowledge_items_mismatch_api,
    patch_expense,
    replace_items_api,
)
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.models import Expense
from app.services.receipt_item_service import acknowledge_items_sum_mismatch


def _create_mismatch_expense(client: TestClient, *, identity) -> int:
    """Create a confirmed expense whose items_sum_status is mismatch_known."""
    created = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": 3500,
            "merchant": "Mismatch Cafe",
            "category": "餐饮",
            "spent_at": "2026-05-04T01:00:00Z",
        },
    )
    assert created.status_code == 200, created.text
    expense_id = int(created.json()["id"])

    response = replace_items_api(
        client,
        expense_id,
        headers=identity.app_headers,
        items=[{"name": "苹果", "kind": "product", "amount_cents": 3800}],
    )
    assert response.status_code == 200, response.text
    assert response.json()["items_sum_status"] == "mismatch_known"
    return expense_id


def test_acknowledge_mismatch_without_token_returns_422(
    client: TestClient, *, identity
) -> None:
    expense_id = _create_mismatch_expense(client, identity=identity)
    response = client.post(
        f"/api/expenses/{expense_id}/items/acknowledge-mismatch",
        headers=identity.app_headers,
        json={},
    )
    assert response.status_code == 422, response.text


def test_acknowledge_mismatch_with_stale_token_returns_409(
    client: TestClient, *, identity
) -> None:
    expense_id = _create_mismatch_expense(client, identity=identity)
    snapshot = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert snapshot.status_code == 200, snapshot.text

    # Peer PATCH bumps updated_at and (more importantly) silently updates
    # other fields. The original "原小票如此" snapshot must not land.
    intervening = patch_expense(
        client,
        expense_id,
        headers=identity.app_headers,
        fields={"merchant": "Mismatch Cafe Renamed"},
    )
    assert intervening.status_code == 200, intervening.text

    response = client.post(
        f"/api/expenses/{expense_id}/items/acknowledge-mismatch",
        headers=identity.app_headers,
        json={"expected_updated_at": snapshot.json()["updated_at"]},
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"] == "state_conflict"

    # Status remains mismatch_known — the stale ack did not land.
    items = client.get(f"/api/expenses/{expense_id}/items", headers=identity.app_headers)
    assert items.json()["items_sum_status"] == "mismatch_known"


def test_acknowledge_mismatch_status_check_preserves_existing_409(
    client: TestClient, *, identity
) -> None:
    """When the row exists but its items_sum_status is no longer
    ``mismatch_known`` (e.g. items now match the amount), the old
    ``items_sum_not_in_mismatch`` 409 still wins over ``state_conflict``.
    This is the existing UX from before PR-2e — preserved through the
    token contract.
    """
    expense_id = _create_mismatch_expense(client, identity=identity)
    snapshot = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)

    # Re-replace items so sum == amount → items_sum_status becomes "match".
    fix = replace_items_api(
        client,
        expense_id,
        headers=identity.app_headers,
        items=[{"name": "苹果", "kind": "product", "amount_cents": 3500}],
    )
    assert fix.status_code == 200, fix.text
    assert fix.json()["items_sum_status"] == "matched"

    # Use the stale snapshot's token. status filter wins over updated_at
    # filter because we surface the status-specific 409 first.
    response = client.post(
        f"/api/expenses/{expense_id}/items/acknowledge-mismatch",
        headers=identity.app_headers,
        json={"expected_updated_at": snapshot.json()["updated_at"]},
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"] == "items_sum_not_in_mismatch"


def test_acknowledge_mismatch_with_fresh_token_succeeds(
    client: TestClient, *, identity
) -> None:
    expense_id = _create_mismatch_expense(client, identity=identity)
    response = acknowledge_items_mismatch_api(
        client, expense_id, headers=identity.app_headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["items_sum_status"] == "mismatch_acknowledged"


def test_two_sessions_acknowledge_race_only_first_writer_wins(
    client: TestClient, *, identity
) -> None:
    expense_id = _create_mismatch_expense(client, identity=identity)
    tenant_id = "owner"

    session_a = SessionLocal()
    session_b = SessionLocal()
    try:
        row_a = session_a.scalar(select(Expense).where(Expense.id == expense_id))
        row_b = session_b.scalar(select(Expense).where(Expense.id == expense_id))
        assert row_a is not None and row_b is not None
        assert row_a.updated_at == row_b.updated_at
        shared_version = row_a.updated_at

        # Session A acknowledges first, which bumps updated_at and flips
        # status away from ``mismatch_known``.
        acknowledge_items_sum_mismatch(
            session_a, expense_id, tenant_id, expected_updated_at=shared_version
        )

        # Session B's stale snapshot can no longer ack — both updated_at
        # AND status filters miss.
        with pytest.raises(AppError) as exc_info:
            acknowledge_items_sum_mismatch(
                session_b, expense_id, tenant_id, expected_updated_at=shared_version
            )
        assert exc_info.value.status_code == 409
        # Either error code is acceptable per the disambiguation contract;
        # status mismatch surfaces as items_sum_not_in_mismatch.
        assert exc_info.value.error in {
            "state_conflict",
            "items_sum_not_in_mismatch",
        }
    finally:
        session_a.close()
        session_b.close()

    items = client.get(f"/api/expenses/{expense_id}/items", headers=identity.app_headers)
    assert items.json()["items_sum_status"] == "mismatch_acknowledged"


def test_acknowledge_mismatch_unknown_expense_returns_404(
    client: TestClient, *, identity
) -> None:
    response = client.post(
        "/api/expenses/9999999/items/acknowledge-mismatch",
        headers=identity.app_headers,
        json={"expected_updated_at": "2026-05-04T00:00:00Z"},
    )
    assert response.status_code == 404, response.text
    assert response.json()["error"] == "expense_not_found"
