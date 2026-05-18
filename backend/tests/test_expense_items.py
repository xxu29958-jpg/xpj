from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import LedgerMember
from api_contract_helpers import upload_png
from conftest import app_headers, gray_app_headers


def _create_manual_expense(
    client: TestClient,
    *,
    amount_cents: int = 1500,
    merchant: str = "Receipt Cafe",
    headers: dict[str, str] | None = None,
) -> int:
    response = client.post(
        "/api/expenses/manual",
        headers=headers or app_headers(),
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
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, object]:
    response = client.put(
        f"/api/expenses/{expense_id}/items",
        headers=headers or app_headers(),
        json={
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
    *,
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
    response = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=app_headers(),
        json={"raw_text": raw_text},
    )
    assert response.status_code == 200, response.json()
    return response.json()


def _demote_owner_ledger_to_viewer() -> None:
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1))
        assert member is not None
        member.role = "viewer"
        db.commit()


def test_expense_items_replace_read_and_reconcile_with_parent_amount(client: TestClient) -> None:
    expense_id = _create_manual_expense(client, amount_cents=1500)

    replaced = _replace_items(client, expense_id)

    assert replaced["expense_id"] == expense_id
    assert replaced["parent_amount_cents"] == 1500
    assert replaced["items_total_amount_cents"] == 1250
    assert replaced["mismatch_cents"] == 250
    assert [item["position"] for item in replaced["items"]] == [0, 1, 2]
    assert replaced["items"][0]["category"] == "餐饮"
    assert replaced["items"][0]["quantity_text"] == "1杯"
    assert replaced["items"][0]["raw_text"] == "拿铁 1杯 5.00"
    assert replaced["items"][0]["is_ocr_draft"] is False

    listed = client.get(f"/api/expenses/{expense_id}/items", headers=app_headers())
    assert listed.status_code == 200, listed.json()
    assert listed.json() == replaced

    detail = client.get(f"/api/expenses/{expense_id}", headers=app_headers())
    assert detail.status_code == 200, detail.json()
    assert "items" not in detail.json()

    second_replace = client.put(
        f"/api/expenses/{expense_id}/items",
        headers=app_headers(),
        json={"items": [{"name": "咖啡豆", "amount_cents": 1500, "category": "购物"}]},
    )
    assert second_replace.status_code == 200, second_replace.json()
    payload = second_replace.json()
    assert payload["items_total_amount_cents"] == 1500
    assert payload["mismatch_cents"] == 0
    assert [item["name"] for item in payload["items"]] == ["咖啡豆"]


def test_expense_items_mismatch_does_not_change_stats_or_export(client: TestClient) -> None:
    expense_id = _create_manual_expense(client, amount_cents=1500)
    replaced = _replace_items(client, expense_id)
    assert replaced["items_total_amount_cents"] == 1250
    assert replaced["mismatch_cents"] == 250

    stats = client.get("/api/stats/monthly?month=2026-05", headers=app_headers())
    assert stats.status_code == 200, stats.json()
    assert stats.json()["total_amount_cents"] == 1500

    exported = client.get(
        "/api/expenses/export.csv?month=2026-05&category=餐饮",
        headers=app_headers(),
    )
    assert exported.status_code == 200, exported.text
    assert "Receipt Cafe" in exported.text
    assert "1500" in exported.text
    assert "1250" not in exported.text


def test_recognize_text_creates_ocr_draft_items(client: TestClient) -> None:
    expense_id = upload_png(client)

    recognized = _recognize_receipt_items(client, expense_id)
    assert recognized["status"] == "pending"
    assert recognized["amount_cents"] == 1250

    listed = client.get(f"/api/expenses/{expense_id}/items", headers=app_headers())
    assert listed.status_code == 200, listed.json()
    payload = listed.json()
    assert payload["parent_amount_cents"] == 1250
    assert payload["items_total_amount_cents"] == 1250
    assert payload["mismatch_cents"] == 0
    assert [item["name"] for item in payload["items"]] == ["拿铁", "三明治"]
    assert [item["quantity_text"] for item in payload["items"]] == ["1杯", "1份"]
    assert [item["amount_cents"] for item in payload["items"]] == [500, 750]
    assert all(item["is_ocr_draft"] is True for item in payload["items"])


def test_recognize_text_replaces_existing_ocr_draft_items(client: TestClient) -> None:
    expense_id = upload_png(client)
    _recognize_receipt_items(client, expense_id)

    response = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=app_headers(),
        json={
            "raw_text": "\n".join(
                [
                    "便利店",
                    "矿泉水 1瓶 2.00",
                    "饭团 1个 6.00",
                    "订单金额 8.00",
                    "支付成功",
                ]
            )
        },
    )
    assert response.status_code == 200, response.json()

    listed = client.get(f"/api/expenses/{expense_id}/items", headers=app_headers())
    assert listed.status_code == 200, listed.json()
    payload = listed.json()
    assert [item["name"] for item in payload["items"]] == ["矿泉水", "饭团"]
    assert [item["amount_cents"] for item in payload["items"]] == [200, 600]
    assert all(item["is_ocr_draft"] is True for item in payload["items"])


def test_recognize_text_without_items_clears_existing_ocr_draft_items(client: TestClient) -> None:
    expense_id = upload_png(client)
    _recognize_receipt_items(client, expense_id)

    response = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=app_headers(),
        json={"raw_text": "星巴克\n支付成功\n谢谢惠顾"},
    )
    assert response.status_code == 200, response.json()

    listed = client.get(f"/api/expenses/{expense_id}/items", headers=app_headers())
    assert listed.status_code == 200, listed.json()
    assert listed.json()["items"] == []


def test_recognize_text_does_not_overwrite_manual_items(client: TestClient) -> None:
    expense_id = upload_png(client)
    _recognize_receipt_items(client, expense_id)

    manual = client.put(
        f"/api/expenses/{expense_id}/items",
        headers=app_headers(),
        json={"items": [{"name": "用户确认明细", "amount_cents": 1250, "category": "餐饮"}]},
    )
    assert manual.status_code == 200, manual.json()
    assert manual.json()["items"][0]["is_ocr_draft"] is False

    _recognize_receipt_items(
        client,
        expense_id,
        item_lines=["矿泉水 1瓶 2.00", "饭团 1个 6.00"],
    )

    listed = client.get(f"/api/expenses/{expense_id}/items", headers=app_headers())
    assert listed.status_code == 200, listed.json()
    payload = listed.json()
    assert [item["name"] for item in payload["items"]] == ["用户确认明细"]
    assert payload["items"][0]["is_ocr_draft"] is False


def test_expense_items_are_tenant_isolated_and_viewer_can_only_read(client: TestClient) -> None:
    owner_expense_id = _create_manual_expense(client, merchant="Owner Items")
    gray_expense_id = _create_manual_expense(
        client,
        merchant="Gray Items",
        headers=gray_app_headers(),
    )
    _replace_items(client, owner_expense_id)

    gray_cross_read = client.get(
        f"/api/expenses/{owner_expense_id}/items",
        headers=gray_app_headers(),
    )
    owner_cross_read = client.get(
        f"/api/expenses/{gray_expense_id}/items",
        headers=app_headers(),
    )
    assert gray_cross_read.status_code == 404
    assert gray_cross_read.json()["error"] == "expense_not_found"
    assert owner_cross_read.status_code == 404
    assert owner_cross_read.json()["error"] == "expense_not_found"

    _demote_owner_ledger_to_viewer()
    viewer_read = client.get(f"/api/expenses/{owner_expense_id}/items", headers=app_headers())
    assert viewer_read.status_code == 200, viewer_read.json()
    assert [item["name"] for item in viewer_read.json()["items"]] == ["拿铁", "三明治", "优惠"]

    viewer_write = client.put(
        f"/api/expenses/{owner_expense_id}/items",
        headers=app_headers(),
        json={"items": [{"name": "不该写入", "amount_cents": 1}]},
    )
    assert viewer_write.status_code == 403
    assert viewer_write.json()["error"] == "permission_denied"


def test_rejected_expense_items_cannot_be_replaced(client: TestClient) -> None:
    expense_id = upload_png(client)
    rejected = client.post(f"/api/expenses/{expense_id}/reject", headers=app_headers())
    assert rejected.status_code == 200, rejected.json()

    response = client.put(
        f"/api/expenses/{expense_id}/items",
        headers=app_headers(),
        json={"items": [{"name": "作废明细", "amount_cents": 100}]},
    )

    assert response.status_code == 404
    assert response.json()["error"] == "expense_not_found"
