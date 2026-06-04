from __future__ import annotations

from uuid import uuid4

from api_contract_helpers import recognize_text_api, reject_expense_api, upload_png
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import LedgerMember


def _create_manual_expense(
    client: TestClient,
    *, identity,
    amount_cents: int = 1500,
    merchant: str = "Receipt Cafe",
    headers: dict[str, str] | None = None,
) -> int:
    response = client.post(
        "/api/expenses/manual",
        headers=headers or identity.app_headers,
        json={
            "amount_cents": amount_cents,
            "merchant": merchant,
            "category": "餐饮",
            "expense_time": "2026-05-04T01:00:00Z",
        },
    )
    assert response.status_code == 200, response.json()
    return int(response.json()["id"])


def _replace_items(
    client: TestClient,
    expense_id: int,
    *, identity,
    headers: dict[str, str] | None = None,
) -> dict[str, object]:
    request_headers = headers or identity.app_headers
    snapshot = client.get(f"/api/expenses/{expense_id}", headers=request_headers)
    assert snapshot.status_code == 200, snapshot.json()
    response = client.put(
        f"/api/expenses/{expense_id}/items",
        headers={**request_headers, "Idempotency-Key": str(uuid4())},
        json={
            "expected_row_version": snapshot.json()["row_version"],
            "items": [
                {
                    "name": "拿铁",
                    "quantity_text": " 1杯 ",
                    "unit_price_cents": 500,
                    "amount_cents": 500,
                    "category": "吃饭",
                    "raw_text": " 拿铁 1杯 5.00 ",
                    "confidence": 0.92,
                },
                {
                    "name": "三明治",
                    "quantity_text": "1份",
                    "unit_price_cents": 750,
                    "amount_cents": 750,
                    "category": "餐饮",
                },
                {
                    "name": "优惠",
                    "category": "其他",
                },
            ]
        },
    )
    assert response.status_code == 200, response.json()
    return response.json()


def _recognize_receipt_items(
    client: TestClient,
    expense_id: int,
    *, identity,
    item_lines: list[str] | None = None,
) -> dict[str, object]:
    raw_text = "\n".join(
        [
            "星巴克",
            *(item_lines or ["拿铁 1杯 5.00", "三明治 1份 7.50"]),
            "订单金额 12.50",
            "支付成功",
        ]
    )
    response = recognize_text_api(
        client, expense_id, headers=identity.app_headers, raw_text=raw_text
    )
    assert response.status_code == 200, response.json()
    return response.json()


def _demote_owner_ledger_to_viewer() -> None:
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1))
        assert member is not None
        member.role = "viewer"
        db.commit()


def test_expense_items_replace_read_and_reconcile_with_parent_amount(client: TestClient, *, identity) -> None:
    expense_id = _create_manual_expense(client, amount_cents=1500, identity=identity)

    replaced = _replace_items(client, expense_id, identity=identity)

    assert replaced["expense_id"] == expense_id
    assert replaced["parent_amount_cents"] == 1500
    assert replaced["items_total_amount_cents"] == 1250
    assert replaced["mismatch_cents"] == 250
    assert [item["position"] for item in replaced["items"]] == [0, 1, 2]
    assert replaced["items"][0]["category"] == "餐饮"
    assert replaced["items"][0]["quantity_text"] == "1杯"
    assert replaced["items"][0]["raw_text"] == "拿铁 1杯 5.00"
    assert replaced["items"][0]["is_ocr_draft"] is False

    listed = client.get(f"/api/expenses/{expense_id}/items", headers=identity.app_headers)
    assert listed.status_code == 200, listed.json()
    assert listed.json() == replaced

    detail = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert detail.status_code == 200, detail.json()
    assert "items" not in detail.json()

    second_replace = client.put(
        f"/api/expenses/{expense_id}/items",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "expected_row_version": detail.json()["row_version"],
            "items": [{"name": "咖啡豆", "amount_cents": 1500, "category": "购物"}],
        },
    )
    assert second_replace.status_code == 200, second_replace.json()
    payload = second_replace.json()
    assert payload["items_total_amount_cents"] == 1500
    assert payload["mismatch_cents"] == 0
    assert [item["name"] for item in payload["items"]] == ["咖啡豆"]


def test_expense_items_replace_response_carries_bumped_parent_row_version(
    client: TestClient, *, identity
) -> None:
    """ADR-0041 self-describing contract: PUT /items returns the *parent*
    expense's row_version, advanced past the value the client sent — so a
    chained client can reuse it without a second GET on the expense."""
    expense_id = _create_manual_expense(client, amount_cents=1500, identity=identity)

    snapshot = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert snapshot.status_code == 200, snapshot.json()
    before = snapshot.json()["row_version"]

    response = client.put(
        f"/api/expenses/{expense_id}/items",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "expected_row_version": before,
            "items": [{"name": "拿铁", "amount_cents": 500, "category": "餐饮"}],
        },
    )
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["row_version"] == before + 1

    # The bumped token in the response must match the expense's current state.
    detail = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert detail.status_code == 200, detail.json()
    assert detail.json()["row_version"] == body["row_version"]

    # GET /items mirrors the parent's current row_version (no extra bump).
    listed = client.get(f"/api/expenses/{expense_id}/items", headers=identity.app_headers)
    assert listed.status_code == 200, listed.json()
    assert listed.json()["row_version"] == body["row_version"]


def test_acknowledge_mismatch_response_carries_bumped_parent_row_version(
    client: TestClient, *, identity
) -> None:
    """ADR-0041 self-describing contract: acknowledge-mismatch bumps the
    parent expense's row_version and the response exposes the new value."""
    expense_id = _create_manual_expense(client, amount_cents=1500, identity=identity)
    # Build a mismatch_known state: items sum (1250) != expense amount (1500).
    _replace_items(client, expense_id, identity=identity)

    snapshot = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert snapshot.status_code == 200, snapshot.json()
    before = snapshot.json()["row_version"]

    response = client.post(
        f"/api/expenses/{expense_id}/items/acknowledge-mismatch",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": before},
    )
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["items_sum_status"] == "mismatch_acknowledged"
    assert body["row_version"] == before + 1

    detail = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert detail.status_code == 200, detail.json()
    assert detail.json()["row_version"] == body["row_version"]


def test_expense_items_mismatch_does_not_change_stats_or_export(client: TestClient, *, identity) -> None:
    expense_id = _create_manual_expense(client, amount_cents=1500, identity=identity)
    replaced = _replace_items(client, expense_id, identity=identity)
    assert replaced["items_total_amount_cents"] == 1250
    assert replaced["mismatch_cents"] == 250

    stats = client.get("/api/stats/monthly?month=2026-05", headers=identity.app_headers)
    assert stats.status_code == 200, stats.json()
    assert stats.json()["total_amount_cents"] == 1500

    exported = client.get(
        "/api/expenses/export.csv?month=2026-05&category=餐饮",
        headers=identity.app_headers,
    )
    assert exported.status_code == 200, exported.text
    assert "Receipt Cafe" in exported.text
    assert "1500" in exported.text
    assert "1250" not in exported.text


def test_recognize_text_creates_ocr_draft_items(client: TestClient, *, identity) -> None:
    expense_id = upload_png(client, identity=identity)

    recognized = _recognize_receipt_items(client, expense_id, identity=identity)
    assert recognized["status"] == "pending"
    assert recognized["amount_cents"] == 1250

    listed = client.get(f"/api/expenses/{expense_id}/items", headers=identity.app_headers)
    assert listed.status_code == 200, listed.json()
    payload = listed.json()
    assert payload["parent_amount_cents"] == 1250
    assert payload["items_total_amount_cents"] == 1250
    assert payload["mismatch_cents"] == 0
    assert [item["name"] for item in payload["items"]] == ["拿铁", "三明治"]
    assert [item["quantity_text"] for item in payload["items"]] == ["1杯", "1份"]
    assert [item["amount_cents"] for item in payload["items"]] == [500, 750]
    assert [item["unit_price_cents"] for item in payload["items"]] == [500, 750]
    assert all(item["is_ocr_draft"] is True for item in payload["items"])


def test_recognize_text_replaces_existing_ocr_draft_items(client: TestClient, *, identity) -> None:
    expense_id = upload_png(client, identity=identity)
    _recognize_receipt_items(client, expense_id, identity=identity)

    response = recognize_text_api(
        client,
        expense_id,
        headers=identity.app_headers,
        raw_text="\n".join(
            [
                "便利店",
                "矿泉水 1瓶 2.00",
                "饭团 1个 6.00",
                "订单金额 8.00",
                "支付成功",
            ]
        ),
    )
    assert response.status_code == 200, response.json()

    listed = client.get(f"/api/expenses/{expense_id}/items", headers=identity.app_headers)
    assert listed.status_code == 200, listed.json()
    payload = listed.json()
    assert [item["name"] for item in payload["items"]] == ["矿泉水", "饭团"]
    assert [item["amount_cents"] for item in payload["items"]] == [200, 600]
    assert [item["unit_price_cents"] for item in payload["items"]] == [200, 600]
    assert all(item["is_ocr_draft"] is True for item in payload["items"])


def test_recognize_text_without_items_clears_existing_ocr_draft_items(client: TestClient, *, identity) -> None:
    expense_id = upload_png(client, identity=identity)
    _recognize_receipt_items(client, expense_id, identity=identity)

    response = recognize_text_api(
        client,
        expense_id,
        headers=identity.app_headers,
        raw_text="星巴克\n支付成功\n谢谢惠顾",
    )
    assert response.status_code == 200, response.json()

    listed = client.get(f"/api/expenses/{expense_id}/items", headers=identity.app_headers)
    assert listed.status_code == 200, listed.json()
    assert listed.json()["items"] == []


def test_recognize_text_does_not_overwrite_manual_items(client: TestClient, *, identity) -> None:
    expense_id = upload_png(client, identity=identity)
    _recognize_receipt_items(client, expense_id, identity=identity)

    manual = client.put(
        f"/api/expenses/{expense_id}/items",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "expected_row_version": client.get(
                f"/api/expenses/{expense_id}", headers=identity.app_headers
            ).json()["row_version"],
            "items": [{"name": "用户确认明细", "amount_cents": 1250, "category": "餐饮"}],
        },
    )
    assert manual.status_code == 200, manual.json()
    assert manual.json()["items"][0]["is_ocr_draft"] is False

    _recognize_receipt_items(
        client,
        expense_id,
        item_lines=["矿泉水 1瓶 2.00", "饭团 1个 6.00"],
     identity=identity)

    listed = client.get(f"/api/expenses/{expense_id}/items", headers=identity.app_headers)
    assert listed.status_code == 200, listed.json()
    payload = listed.json()
    assert [item["name"] for item in payload["items"]] == ["用户确认明细"]
    assert payload["items"][0]["is_ocr_draft"] is False


def test_expense_items_are_tenant_isolated_and_viewer_can_only_read(client: TestClient, *, identity) -> None:
    owner_expense_id = _create_manual_expense(client, merchant="Owner Items", identity=identity)
    gray_expense_id = _create_manual_expense(
        client,
        merchant="Gray Items",
        headers=identity.gray_app_headers,
     identity=identity)
    _replace_items(client, owner_expense_id, identity=identity)

    gray_cross_read = client.get(
        f"/api/expenses/{owner_expense_id}/items",
        headers=identity.gray_app_headers,
    )
    owner_cross_read = client.get(
        f"/api/expenses/{gray_expense_id}/items",
        headers=identity.app_headers,
    )
    assert gray_cross_read.status_code == 404
    assert gray_cross_read.json()["error"] == "expense_not_found"
    assert owner_cross_read.status_code == 404
    assert owner_cross_read.json()["error"] == "expense_not_found"

    _demote_owner_ledger_to_viewer()
    viewer_read = client.get(f"/api/expenses/{owner_expense_id}/items", headers=identity.app_headers)
    assert viewer_read.status_code == 200, viewer_read.json()
    assert [item["name"] for item in viewer_read.json()["items"]] == ["拿铁", "三明治", "优惠"]
    viewer_snapshot = client.get(
        f"/api/expenses/{owner_expense_id}", headers=identity.app_headers
    )
    assert viewer_snapshot.status_code == 200, viewer_snapshot.json()

    viewer_write = client.put(
        f"/api/expenses/{owner_expense_id}/items",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "expected_row_version": viewer_snapshot.json()["row_version"],
            "items": [{"name": "不该写入", "amount_cents": 1}],
        },
    )
    assert viewer_write.status_code == 403
    assert viewer_write.json()["error"] == "permission_denied"


def test_rejected_expense_items_cannot_be_replaced(client: TestClient, *, identity) -> None:
    expense_id = upload_png(client, identity=identity)
    rejected = reject_expense_api(client, expense_id, headers=identity.app_headers)
    assert rejected.status_code == 200, rejected.json()

    response = client.put(
        f"/api/expenses/{expense_id}/items",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "expected_row_version": rejected.json()["row_version"],
            "items": [{"name": "作废明细", "amount_cents": 100}],
        },
    )

    assert response.status_code == 404
    assert response.json()["error"] == "expense_not_found"
