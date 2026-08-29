"""Allocation invariant at the direct household split command consumer."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.expense_split_test_support import bearer, family_split_fixture


def test_expense_splits_reject_overallocation_without_mutating_parent(
    client: TestClient,
    *,
    identity,
) -> None:
    (
        _family_id,
        owner_token,
        _member_token,
        _viewer_token,
        expense_id,
        owner_member_id,
        member_member_id,
    ) = family_split_fixture(client, identity=identity)
    headers = bearer(owner_token)
    before = client.get(f"/api/expenses/{expense_id}", headers=headers).json()

    rejected = client.put(
        f"/api/expenses/{expense_id}/splits",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={
            "expected_row_version": before["row_version"],
            "splits": [
                {"member_id": owner_member_id, "amount_cents": 6000},
                {"member_id": member_member_id, "amount_cents": 5000},
            ],
        },
    )

    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["error"] == "expense_split_total_exceeds_parent"
    current = client.get(f"/api/expenses/{expense_id}", headers=headers).json()
    assert current["row_version"] == before["row_version"]
    splits = client.get(f"/api/expenses/{expense_id}/splits", headers=headers).json()
    assert splits["splits"] == []
