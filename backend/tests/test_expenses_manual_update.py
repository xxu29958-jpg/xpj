from __future__ import annotations

from uuid import UUID

from api_contract_helpers import (
    patch_expense,
    upload_png,
)
from fastapi.testclient import TestClient


def test_manual_expense_create_contract(client: TestClient, *, identity) -> None:
    response = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": 1280,
            "merchant": "手动早餐",
            "category": "餐饮",
            "note": "上班路上",
            "expense_time": "2026-05-04T00:30:00Z",
            "tags": "手动",
            "value_score": 4,
            "regret_score": 1,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "confirmed"
    UUID(payload["public_id"])
    assert payload["source"] == "手动记账"
    assert payload["amount_cents"] == 1280
    assert payload["image_path"] is None
    assert payload["confirmed_at"].endswith("Z")

    confirmed = client.get(
        "/api/expenses/confirmed?month=2026-05&category=餐饮", headers=identity.app_headers
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["total"] == 1

    stats = client.get("/api/stats/monthly?month=2026-05", headers=identity.app_headers)
    assert stats.status_code == 200
    assert stats.json()["total_amount_cents"] == 1280

    missing_amount = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={"merchant": "无金额"},
    )
    assert missing_amount.status_code == 400
    assert missing_amount.json()["error"] == "amount_required"


def test_confirmed_batch_update_scopes_and_updates_tags(client: TestClient, *, identity) -> None:
    def _manual(headers: dict[str, str], merchant: str, category: str) -> int:
        response = client.post(
            "/api/expenses/manual",
            headers=headers,
            json={
                "amount_cents": 1200,
                "merchant": merchant,
                "category": category,
                "expense_time": "2026-05-05T12:00:00Z",
            },
        )
        assert response.status_code == 200, response.json()
        return int(response.json()["id"])

    def _updated_at(expense_id: int, headers: dict[str, str]) -> str:
        response = client.get(f"/api/expenses/{expense_id}", headers=headers)
        assert response.status_code == 200, response.text
        return str(response.json()["row_version"])

    first_id = _manual(identity.app_headers, "Batch Coffee A", "OldCat")
    second_id = _manual(identity.app_headers, "Batch Coffee B", "OldCat")
    other_ledger_id = _manual(identity.gray_app_headers, "Batch Other Ledger", "GrayCat")
    pending_id = upload_png(client, identity=identity)
    expected_row_version_by_id = {
        first_id: _updated_at(first_id, identity.app_headers),
        second_id: _updated_at(second_id, identity.app_headers),
        other_ledger_id: _updated_at(other_ledger_id, identity.gray_app_headers),
        pending_id: _updated_at(pending_id, identity.app_headers),
    }

    response = client.post(
        "/api/expenses/confirmed/batch-update",
        headers=identity.app_headers,
        json={
            "expense_ids": [first_id, second_id, pending_id, other_ledger_id, first_id],
            "expected_row_version_by_id": expected_row_version_by_id,
            "category": "Family Meals",
            "tags": "weekend, shared, weekend",
        },
    )
    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload == {
        "requested_count": 4,
        "updated_count": 2,
        "skipped_not_found": 1,
        "skipped_not_confirmed": 1,
    }

    for expense_id in [first_id, second_id]:
        detail = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
        assert detail.status_code == 200
        assert detail.json()["category"] == "Family Meals"
        assert detail.json()["tags"] == "weekend, shared"

    pending_detail = client.get(f"/api/expenses/{pending_id}", headers=identity.app_headers)
    assert pending_detail.status_code == 200
    assert pending_detail.json()["category"] != "Family Meals"

    other_detail = client.get(f"/api/expenses/{other_ledger_id}", headers=identity.gray_app_headers)
    assert other_detail.status_code == 200
    assert other_detail.json()["category"] == "GrayCat"


def test_confirmed_batch_update_stale_token_returns_409_without_partial_update(
    client: TestClient, *, identity
) -> None:
    def _manual(merchant: str, category: str) -> int:
        response = client.post(
            "/api/expenses/manual",
            headers=identity.app_headers,
            json={
                "amount_cents": 1200,
                "merchant": merchant,
                "category": category,
                "expense_time": "2026-05-05T12:00:00Z",
            },
        )
        assert response.status_code == 200, response.json()
        return int(response.json()["id"])

    def _detail(expense_id: int) -> dict:
        response = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
        assert response.status_code == 200, response.text
        return response.json()

    first_id = _manual("Batch Stale A", "Initial A")
    second_id = _manual("Batch Stale B", "Initial B")
    first_snapshot = _detail(first_id)
    second_snapshot = _detail(second_id)

    intervening = patch_expense(
        client,
        first_id,
        headers=identity.app_headers,
        fields={"category": "Intervening"},
    )
    assert intervening.status_code == 200, intervening.text

    response = client.post(
        "/api/expenses/confirmed/batch-update",
        headers=identity.app_headers,
        json={
            "expense_ids": [first_id, second_id],
            "expected_row_version_by_id": {
                first_id: first_snapshot["row_version"],
                second_id: second_snapshot["row_version"],
            },
            "category": "Should Not Land",
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"] == "state_conflict"

    assert _detail(first_id)["category"] == "Intervening"
    assert _detail(second_id)["category"] == "Initial B"


def test_expense_update_normalizes_user_text(client: TestClient, *, identity) -> None:
    expense_id = upload_png(client, identity=identity)

    response = patch_expense(
        client,
        expense_id,
        headers=identity.app_headers,
        fields={
            "amount_cents": 990,
            "merchant": "  便利店  ",
            "category": "  生活  ",
            "note": "  夜宵  ",
            "tags": "  真机联调  ",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["merchant"] == "便利店"
    assert payload["category"] == "生活"
    assert payload["note"] == "夜宵"
    assert payload["tags"] == "真机联调"

    response = patch_expense(
        client,
        expense_id,
        headers=identity.app_headers,
        fields={"category": "吃饭"},
    )
    assert response.status_code == 200
    assert response.json()["category"] == "餐饮"

    response = patch_expense(
        client,
        expense_id,
        headers=identity.app_headers,
        fields={
            "merchant": "   ",
            "category": "   ",
            "note": None,
            "tags": "   ",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["merchant"] is None
    assert payload["category"] == "其他"
    assert payload["note"] == ""
    assert payload["tags"] is None
