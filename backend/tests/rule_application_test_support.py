"""Existing rule-application HTTP preparation shared by its real consumers."""

from uuid import uuid4

from api_contract_helpers import patch_expense
from fastapi.testclient import TestClient


def set_pending_merchant(client: TestClient, expense_id: int, merchant: str, *, identity) -> None:
    response = patch_expense(
        client,
        expense_id,
        headers=identity.app_headers,
        fields={"merchant": merchant, "amount_cents": 3800},
    )
    assert response.status_code == 200


def apply_pending_rules(client: TestClient, *, identity, max_scan: int = 500):
    preview = client.post(
        f"/api/rules/apply-pending/preview?max_scan={max_scan}",
        headers=identity.app_headers,
    )
    assert preview.status_code == 200, preview.json()
    token = preview.json()["preview_token"]
    return client.post(
        f"/api/rules/apply-pending?max_scan={max_scan}",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"confirm": True, "preview_token": token},
    )
