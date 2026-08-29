"""Web confirmed-correction preservation of hidden OCR item provenance."""

from fastapi.testclient import TestClient


def test_web_item_correction_preserves_hidden_ocr_provenance(
    web_client: TestClient,
    *,
    identity,
) -> None:
    created = web_client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": 1234,
            "merchant": "OCR 来源保留测试",
            "category": "餐饮",
            "expense_time": "2026-05-04T12:00:00Z",
        },
    )
    assert created.status_code == 200, created.text
    expense_id = int(created.json()["id"])
    seeded = web_client.post(
        f"/api/expenses/{expense_id}/corrections",
        headers={**identity.app_headers, "Idempotency-Key": "seed-web-item-provenance"},
        json={
            "expected_row_version": created.json()["row_version"],
            "reason": "补入 OCR 明细来源",
            "items": [
                {
                    "name": "稍后删除的识别行",
                    "kind": "product",
                    "amount_cents": 0,
                    "raw_text": "OCR 原始行：应被删除",
                    "confidence": 0.41,
                },
                {
                    "name": "识别名称",
                    "kind": "product",
                    "amount_cents": 1234,
                    "raw_text": "OCR 原始行：识别名称 12.34",
                    "confidence": 0.87,
                },
            ],
        },
    )
    assert seeded.status_code == 201, seeded.text

    response = web_client.post(
        f"/web/expenses/{expense_id}/corrections",
        data={
            "ledger_id": "owner",
            "reason": "修正 OCR 识别名称",
            "expected_row_version": str(seeded.json()["expense"]["row_version"]),
            "item_name": ["", "人工修正名称"],
            "item_kind": ["product", "product"],
            "item_quantity": ["", ""],
            "item_unit_price_yuan": ["", ""],
            "item_amount_yuan": ["", "12.34"],
            "item_category": ["", ""],
        },
        follow_redirects=False,
    )

    assert response.status_code == 303, response.text
    current = web_client.get(
        f"/api/expenses/{expense_id}/items",
        headers=identity.app_headers,
    )
    assert current.status_code == 200, current.text
    assert len(current.json()["items"]) == 1
    item = current.json()["items"][0]
    assert item["name"] == "人工修正名称"
    assert item["raw_text"] == "OCR 原始行：识别名称 12.34"
    assert item["confidence"] == 0.87
