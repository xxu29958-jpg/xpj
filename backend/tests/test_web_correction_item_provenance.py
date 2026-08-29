"""Web confirmed-correction preservation of hidden OCR item provenance."""

from fastapi.testclient import TestClient


def _item_form_data(items: list[dict], *, names: list[str]) -> dict[str, list[str]]:
    kept = [bool(name.strip()) for name in names]

    def amount_yuan(item: dict, keep: bool) -> str:
        if not keep or item["amount_cents"] is None:
            return ""
        cents = abs(int(item["amount_cents"]))
        return f"{cents // 100}.{cents % 100:02d}"

    return {
        "item_public_id": [item["public_id"] for item in items],
        "item_name": names,
        "item_kind": [item["kind"] for item in items],
        "item_quantity": [
            (item["quantity_text"] or "") if keep else ""
            for item, keep in zip(items, kept, strict=True)
        ],
        "item_unit_price_yuan": ["" for _item in items],
        "item_amount_yuan": [amount_yuan(item, keep) for item, keep in zip(items, kept, strict=True)],
        "item_category": [
            (item["category"] or "") if keep else ""
            for item, keep in zip(items, kept, strict=True)
        ],
    }


def _seed_ocr_items(
    web_client: TestClient,
    identity: object,
    *,
    merchant: str,
    idempotency_key: str,
) -> tuple[int, dict, list[dict]]:
    created = web_client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": 1234,
            "merchant": merchant,
            "category": "餐饮",
            "expense_time": "2026-05-04T12:00:00Z",
        },
    )
    assert created.status_code == 200, created.text
    expense_id = int(created.json()["id"])
    seeded = web_client.post(
        f"/api/expenses/{expense_id}/corrections",
        headers={**identity.app_headers, "Idempotency-Key": idempotency_key},
        json={
            "expected_row_version": created.json()["row_version"],
            "reason": "补入两行 OCR 来源",
            "items": [
                {
                    "name": "识别行 A",
                    "kind": "product",
                    "amount_cents": 0,
                    "raw_text": "OCR A",
                    "confidence": 0.41,
                },
                {
                    "name": "识别行 B",
                    "kind": "product",
                    "amount_cents": 1234,
                    "raw_text": "OCR B 12.34",
                    "confidence": 0.87,
                },
            ],
        },
    )
    assert seeded.status_code == 201, seeded.text
    items_response = web_client.get(
        f"/api/expenses/{expense_id}/items",
        headers=identity.app_headers,
    )
    assert items_response.status_code == 200, items_response.text
    return expense_id, seeded.json(), items_response.json()["items"]


def _concurrent_replace_with_b(
    web_client: TestClient,
    identity: object,
    *,
    expense_id: int,
    row_version: int,
) -> dict:
    response = web_client.post(
        f"/api/expenses/{expense_id}/corrections",
        headers={**identity.app_headers, "Idempotency-Key": "concurrent-web-item-occ"},
        json={
            "expected_row_version": row_version,
            "reason": "另一端删除 A",
            "items": [
                {
                    "name": "并发后的 B",
                    "kind": "product",
                    "amount_cents": 1234,
                    "raw_text": "OCR B 12.34",
                    "confidence": 0.87,
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_web_item_correction_preserves_hidden_ocr_provenance(
    web_client: TestClient,
    *,
    identity,
) -> None:
    expense_id, seeded, seeded_items = _seed_ocr_items(
        web_client,
        identity,
        merchant="OCR 来源保留测试",
        idempotency_key="seed-web-item-provenance",
    )
    correction_page = web_client.get(
        f"/web/expenses/{expense_id}/correct?ledger_id=owner"
    )
    assert correction_page.status_code == 200, correction_page.text
    for item in seeded_items:
        assert f'name="item_public_id" value="{item["public_id"]}"' in correction_page.text

    response = web_client.post(
        f"/web/expenses/{expense_id}/corrections",
        data={
            "ledger_id": "owner",
            "reason": "修正 OCR 识别名称",
            "expected_row_version": str(seeded["expense"]["row_version"]),
            "item_public_id": [item["public_id"] for item in seeded_items],
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
    assert item["raw_text"] == "OCR B 12.34"
    assert item["confidence"] == 0.87


def test_web_item_correction_rejects_stale_row_identities_before_retry(
    web_client: TestClient,
    *,
    identity,
) -> None:
    expense_id, seeded, old_items = _seed_ocr_items(
        web_client,
        identity,
        merchant="OCR 并发来源测试",
        idempotency_key="seed-web-item-occ",
    )
    concurrent = _concurrent_replace_with_b(
        web_client,
        identity,
        expense_id=expense_id,
        row_version=seeded["expense"]["row_version"],
    )

    stale_form = {
        "ledger_id": "owner",
        "reason": "从旧页面编辑 B",
        "expected_row_version": str(seeded["expense"]["row_version"]),
        "idempotency_key": "web-item-occ-retry",
        **_item_form_data(old_items, names=["", "用户编辑后的 B"]),
    }
    conflict = web_client.post(
        f"/web/expenses/{expense_id}/corrections",
        data=stale_form,
        follow_redirects=False,
    )
    assert conflict.status_code == 409, conflict.text

    # Even with the refreshed parent token, the stale row identities may not be
    # rebound positionally to the concurrent writer's replacement rows.
    stale_form["expected_row_version"] = str(concurrent["expense"]["row_version"])
    stale_retry = web_client.post(
        f"/web/expenses/{expense_id}/corrections",
        data=stale_form,
        follow_redirects=False,
    )
    assert stale_retry.status_code == 409, stale_retry.text
    assert "明细已在其它端变化" in stale_retry.text

    current_items_response = web_client.get(
        f"/api/expenses/{expense_id}/items",
        headers=identity.app_headers,
    )
    assert current_items_response.status_code == 200, current_items_response.text
    current_items = current_items_response.json()["items"]
    assert len(current_items) == 1
    assert current_items[0]["name"] == "并发后的 B"
    assert current_items[0]["raw_text"] == "OCR B 12.34"
    assert current_items[0]["confidence"] == 0.87

    recovery = web_client.post(
        f"/web/expenses/{expense_id}/corrections",
        data={
            "ledger_id": "owner",
            "reason": "按最新明细重新编辑 B",
            "expected_row_version": str(current_items_response.json()["row_version"]),
            "idempotency_key": "web-item-occ-retry",
            **_item_form_data(current_items, names=["用户编辑后的 B"]),
        },
        follow_redirects=False,
    )
    assert recovery.status_code == 303, recovery.text
    recovered = web_client.get(
        f"/api/expenses/{expense_id}/items",
        headers=identity.app_headers,
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["items"][0]["name"] == "用户编辑后的 B"
    assert recovered.json()["items"][0]["raw_text"] == "OCR B 12.34"
    assert recovered.json()["items"][0]["confidence"] == 0.87
