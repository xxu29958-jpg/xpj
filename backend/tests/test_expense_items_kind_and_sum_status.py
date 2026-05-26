"""ADR-0035 PR-1: ExpenseItem.kind enum + Expense.items_sum_status state machine."""

from __future__ import annotations

from api_contract_helpers import acknowledge_items_mismatch_api
from fastapi.testclient import TestClient


def _create_manual_expense(
    client: TestClient,
    *,
    identity,
    amount_cents: int = 3500,
    merchant: str = "Receipt Cafe",
) -> int:
    response = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": amount_cents,
            "merchant": merchant,
            "category": "餐饮",
            "expense_time": "2026-05-04T01:00:00Z",
        },
    )
    assert response.status_code == 200, response.json()
    return int(response.json()["id"])


def _put_items(client: TestClient, *, identity, expense_id: int, items: list[dict]):
    snapshot = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert snapshot.status_code == 200, snapshot.json()
    return client.put(
        f"/api/expenses/{expense_id}/items",
        headers=identity.app_headers,
        json={"expected_updated_at": snapshot.json()["updated_at"], "items": items},
    )


# --- Schema-level sign-by-kind validation ---------------------------------


def test_discount_kind_rejects_positive_amount(client: TestClient, *, identity) -> None:
    expense_id = _create_manual_expense(client, identity=identity)
    response = _put_items(
        client,
        identity=identity,
        expense_id=expense_id,
        items=[
            {"name": "优惠", "kind": "discount", "amount_cents": 300},  # 应该 ≤0
        ],
    )
    assert response.status_code == 422


def test_product_kind_rejects_negative_amount(client: TestClient, *, identity) -> None:
    expense_id = _create_manual_expense(client, identity=identity)
    response = _put_items(
        client,
        identity=identity,
        expense_id=expense_id,
        items=[
            {"name": "苹果", "kind": "product", "amount_cents": -100},  # 应该 ≥0
        ],
    )
    assert response.status_code == 422


def test_tax_kind_rejects_negative_amount(client: TestClient, *, identity) -> None:
    expense_id = _create_manual_expense(client, identity=identity)
    response = _put_items(
        client,
        identity=identity,
        expense_id=expense_id,
        items=[
            {"name": "VAT", "kind": "tax", "amount_cents": -50},  # 应该 ≥0
        ],
    )
    assert response.status_code == 422


def test_kind_defaults_to_product(client: TestClient, *, identity) -> None:
    expense_id = _create_manual_expense(client, identity=identity)
    response = _put_items(
        client,
        identity=identity,
        expense_id=expense_id,
        items=[
            {"name": "苹果", "amount_cents": 1000},  # 不传 kind
        ],
    )
    assert response.status_code == 200, response.json()
    item = response.json()["items"][0]
    assert item["kind"] == "product"


# --- items_sum_status computation ----------------------------------------


def test_items_sum_status_matched_with_discount(client: TestClient, *, identity) -> None:
    """1 product (¥38) + 1 discount (-¥3) sums to ¥35, equals expense.amount_cents."""
    expense_id = _create_manual_expense(client, identity=identity, amount_cents=3500)
    response = _put_items(
        client,
        identity=identity,
        expense_id=expense_id,
        items=[
            {"name": "正餐套餐", "kind": "product", "amount_cents": 3800},
            {"name": "VIP 折扣", "kind": "discount", "amount_cents": -300},
        ],
    )
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["items_sum_status"] == "matched"
    assert body["items_total_amount_cents"] == 3500
    assert body["mismatch_cents"] == 0


def test_items_sum_status_mismatch_known(client: TestClient, *, identity) -> None:
    """Items sum ¥38, expense ¥35 → mismatch_known."""
    expense_id = _create_manual_expense(client, identity=identity, amount_cents=3500)
    response = _put_items(
        client,
        identity=identity,
        expense_id=expense_id,
        items=[
            {"name": "苹果", "kind": "product", "amount_cents": 3800},
        ],
    )
    assert response.status_code == 200
    body = response.json()
    assert body["items_sum_status"] == "mismatch_known"
    assert body["mismatch_cents"] == -300  # expense 35 - items 38 = -3


def test_items_sum_status_no_items_when_empty(client: TestClient, *, identity) -> None:
    expense_id = _create_manual_expense(client, identity=identity)
    response = _put_items(client, identity=identity, expense_id=expense_id, items=[])
    assert response.status_code == 200
    assert response.json()["items_sum_status"] == "no_items"


# --- mismatch_known → mismatch_acknowledged --------------------------------


def test_acknowledge_mismatch_transition(client: TestClient, *, identity) -> None:
    expense_id = _create_manual_expense(client, identity=identity, amount_cents=3500)
    _put_items(
        client,
        identity=identity,
        expense_id=expense_id,
        items=[{"name": "苹果", "kind": "product", "amount_cents": 3800}],
    )
    response = acknowledge_items_mismatch_api(
        client, expense_id, headers=identity.app_headers
    )
    assert response.status_code == 200, response.json()
    assert response.json()["items_sum_status"] == "mismatch_acknowledged"


def test_acknowledge_mismatch_rejects_when_matched(client: TestClient, *, identity) -> None:
    expense_id = _create_manual_expense(client, identity=identity, amount_cents=3500)
    _put_items(
        client,
        identity=identity,
        expense_id=expense_id,
        items=[{"name": "苹果", "kind": "product", "amount_cents": 3500}],
    )
    response = acknowledge_items_mismatch_api(
        client, expense_id, headers=identity.app_headers
    )
    assert response.status_code == 409
    assert response.json()["error"] == "items_sum_not_in_mismatch"


def test_acknowledge_persists_across_edit(client: TestClient, *, identity) -> None:
    """已 acknowledged 的 mismatch 在 item 再编辑时如果差异仍存在，保留状态不回退到 mismatch_known。"""
    expense_id = _create_manual_expense(client, identity=identity, amount_cents=3500)
    # 先制造一个 mismatch
    _put_items(
        client,
        identity=identity,
        expense_id=expense_id,
        items=[{"name": "苹果", "kind": "product", "amount_cents": 3800}],
    )
    # acknowledge
    acknowledge_items_mismatch_api(client, expense_id, headers=identity.app_headers)
    # 再改 items 但仍然 mismatch
    response = _put_items(
        client,
        identity=identity,
        expense_id=expense_id,
        items=[
            {"name": "苹果", "kind": "product", "amount_cents": 3800},
            {"name": "饮料", "kind": "product", "amount_cents": 200},
        ],
    )
    assert response.status_code == 200
    # 现在 sum = 4000, expense = 3500，仍 mismatch；但 acknowledge 状态保留
    assert response.json()["items_sum_status"] == "mismatch_acknowledged"
