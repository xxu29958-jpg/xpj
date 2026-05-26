from __future__ import annotations

import pytest
from api_contract_helpers import (
    patch_expense,
    reject_expense_api,
    upload_png,
)
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.errors import AppError
from app.models import Expense
from app.services.expense_service import confirm_expense, reject_expense


def test_reject_removes_expense_from_pending_without_confirming(
    client: TestClient, *, identity,
) -> None:
    expense_id = upload_png(client, identity=identity)

    response = reject_expense_api(client, expense_id, headers=identity.app_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "rejected"
    assert payload["confirmed_at"] is None

    pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    assert pending.status_code == 200
    assert all(item["id"] != expense_id for item in pending.json())

    confirmed = client.get(
        "/api/expenses/confirmed?month=2026-05", headers=identity.app_headers
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["total"] == 0


def test_stale_reject_cannot_overwrite_confirmed_expense(client: TestClient, *, identity) -> None:
    expense_id = upload_png(client, identity=identity)
    response = patch_expense(
        client,
        expense_id,
        headers=identity.app_headers,
        fields={"amount_cents": 3680, "merchant": "A", "category": "餐饮"},
    )
    assert response.status_code == 200

    confirm_db = SessionLocal()
    reject_db = SessionLocal()
    try:
        confirm_row = confirm_db.get(Expense, expense_id)
        reject_row = reject_db.get(Expense, expense_id)
        assert confirm_row is not None
        assert reject_row is not None
        # Both sessions hold the same pre-confirm snapshot — the
        # token they'll pass to the state-machine endpoints.
        shared_version = confirm_row.updated_at
        confirmed = confirm_expense(
            confirm_db,
            expense_id,
            "owner",
            expected_updated_at=shared_version,
        )
        assert confirmed.status == "confirmed"

        # Writer B replays the stale shared_version. The row has moved
        # to "confirmed" (terminal, not in pending); atomic UPDATE
        # WHERE status="pending" finds nothing and the service maps
        # that to ``expense_not_found`` 404.
        with pytest.raises(AppError) as error:
            reject_expense(
                reject_db,
                expense_id,
                "owner",
                expected_updated_at=shared_version,
            )
        assert error.value.error == "expense_not_found"
        assert error.value.status_code == 404
    finally:
        confirm_db.close()
        reject_db.close()

    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        assert expense.status == "confirmed"
        assert expense.confirmed_at is not None
        assert expense.rejected_at is None


def test_reject_is_idempotent_for_already_rejected_expense(client: TestClient, *, identity) -> None:
    expense_id = upload_png(client, identity=identity)
    first = reject_expense_api(client, expense_id, headers=identity.app_headers)
    assert first.status_code == 200

    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        rejected_at = expense.rejected_at
        updated_at = expense.updated_at

    second = reject_expense_api(client, expense_id, headers=identity.app_headers)
    assert second.status_code == 200
    assert second.json()["status"] == "rejected"

    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        assert expense.rejected_at == rejected_at
        assert expense.updated_at == updated_at
