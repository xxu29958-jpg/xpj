from __future__ import annotations

import pytest
from api_contract_helpers import (
    confirm_expense_api,
    patch_expense,
    reject_expense_api,
    upload_png,
)
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.errors import AppError
from app.models import Expense
from app.services.expense_service import confirm_expense, reject_expense
from tests._confirmed_stream_test_support import confirmed_expense_roots


def test_reject_removes_expense_from_pending_without_confirming(
    client: TestClient,
    *,
    identity,
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

    confirmed = client.get("/api/expenses/confirmed?month=2026-05", headers=identity.app_headers)
    assert confirmed.status_code == 200
    assert confirmed.json()["total"] == 0


def test_reject_confirmed_expense_requires_refund_or_reversal_fact(client: TestClient, *, identity) -> None:
    expense_id = upload_png(client, identity=identity)
    response = patch_expense(
        client,
        expense_id,
        headers=identity.app_headers,
        fields={"amount_cents": 3500, "merchant": "Jack", "category": "其他"},
    )
    assert response.status_code == 200

    confirmed = confirm_expense_api(client, expense_id, headers=identity.app_headers)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "confirmed"

    rejected = reject_expense_api(client, expense_id, headers=identity.app_headers)
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["error"] == "expense_reversal_required"

    confirmed_page = client.get("/api/expenses/confirmed", headers=identity.app_headers)
    assert confirmed_page.status_code == 200
    assert confirmed_page.json()["total"] == 1
    assert any(item["id"] == expense_id for item in confirmed_expense_roots(confirmed_page.json()))

    detail = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert detail.status_code == 200
    assert detail.json()["status"] == "confirmed"
    assert detail.json()["amount_cents"] == 3500


@pytest.mark.real_db
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
        shared_version = confirm_row.row_version
        confirmed = confirm_expense(
            confirm_db,
            expense_id,
            "owner",
            expected_row_version=shared_version,
        )
        assert confirmed.status == "confirmed"

        # Confirmed facts no longer enter the workflow recycle bin. A stale
        # reject intent is routed to the same explicit reversal requirement.
        with pytest.raises(AppError) as error:
            reject_expense(
                reject_db,
                expense_id,
                "owner",
                expected_row_version=shared_version,
            )
        assert error.value.error == "expense_reversal_required"
        assert error.value.status_code == 409
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
