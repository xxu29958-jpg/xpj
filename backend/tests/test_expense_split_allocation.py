"""Allocation invariant at the direct household split command consumer."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Expense
from tests.api_contract_helpers import confirm_expense_api, patch_expense
from tests.expense_split_test_support import bearer, family_split_fixture, replace_splits


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


def test_pending_amount_patch_rejects_existing_split_overallocation(
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
    replace_splits(
        client,
        owner_token,
        expense_id,
        owner_member_id,
        member_member_id,
        owner_amount_cents=6000,
        member_amount_cents=3000,
    )
    before = client.get(f"/api/expenses/{expense_id}", headers=headers).json()

    rejected = patch_expense(
        client,
        expense_id,
        headers=headers,
        fields={"amount_cents": 8000},
    )

    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["error"] == "expense_split_total_exceeds_parent"
    current = client.get(f"/api/expenses/{expense_id}", headers=headers).json()
    assert current["amount_cents"] == before["amount_cents"]
    assert current["row_version"] == before["row_version"]


def test_confirmation_rejects_preexisting_pending_split_overallocation(
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
    replace_splits(
        client,
        owner_token,
        expense_id,
        owner_member_id,
        member_member_id,
        owner_amount_cents=6000,
        member_amount_cents=4000,
    )
    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.id == expense_id))
        assert expense is not None
        expense.amount_cents = 9000
        db.commit()

    rejected = confirm_expense_api(client, expense_id, headers=headers)

    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["error"] == "expense_split_total_exceeds_parent"
    current = client.get(f"/api/expenses/{expense_id}", headers=headers).json()
    assert current["status"] == "pending"
