"""Shared fixture and markup helpers for Web bulk-action tests."""

from __future__ import annotations

from api_contract_helpers import web_save_expense
from fastapi.testclient import TestClient


def create_pending(client: TestClient, *, identity) -> int:
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    response = client.post(
        f"/u/{identity.upload_key}",
        headers={"Content-Type": "image/png"},
        content=png,
    )
    assert response.status_code == 200, response.text
    return int(response.json()["id"])


def seed_pending_with_amount(
    web_client: TestClient,
    amount_yuan: str = "10.00",
    merchant: str = "测试",
    *,
    identity,
) -> int:
    expense_id = create_pending(web_client, identity=identity)
    response = web_save_expense(
        web_client,
        expense_id,
        identity=identity,
        data={
            "amount_yuan": amount_yuan,
            "merchant": merchant,
            "category": "其他",
            "note": "",
            "ledger_id": "owner",
        },
    )
    assert response.status_code in {303, 307}, response.text
    return expense_id


def row_version(
    web_client: TestClient,
    expense_id: int,
    *,
    identity,
) -> int:
    response = web_client.get(
        f"/api/expenses/{expense_id}",
        headers=identity.app_headers,
    )
    assert response.status_code == 200, response.text
    return int(response.json()["row_version"])


def bulk_snapshot_fields(
    web_client: TestClient,
    expense_ids: list[int],
    *,
    identity,
) -> dict[str, list[str]]:
    return {
        "expense_ids": [str(expense_id) for expense_id in expense_ids],
        "expected_row_version": [
            str(row_version(web_client, expense_id, identity=identity)) for expense_id in expense_ids
        ],
    }
