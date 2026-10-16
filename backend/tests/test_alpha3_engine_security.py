"""v0.4-alpha3 Smart Ledger Engine — Rules preview/apply + Recurring candidates."""
from __future__ import annotations

from uuid import uuid4

from api_contract_helpers import upload_png
from fastapi.testclient import TestClient


def test_alpha3_endpoints_no_secret_leak(client: TestClient, *, identity) -> None:
    upload_png(client, identity=identity)
    preview_for_apply = client.post("/api/rules/apply-pending/preview", headers=identity.app_headers)
    assert preview_for_apply.status_code == 200
    preview_token = preview_for_apply.json()["preview_token"]
    for path, method, body in [
        ("/api/rules/preview", "POST", {"keyword": "x", "target_category": "餐饮"}),
        ("/api/rules/apply-pending/preview", "POST", None),
        (
            "/api/rules/apply-pending",
            "POST",
            {"confirm": True, "preview_token": preview_token},
        ),
        ("/api/insights/recurring-candidates", "GET", None),
    ]:
        if method == "GET":
            response = client.get(path, headers=identity.app_headers)
        else:
            headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())} if body and body.get("confirm") else identity.app_headers
            response = client.post(path, headers=headers, json=body)
        assert response.status_code == 200
        text = response.text
        assert "token_hash" not in text
        assert "upload_key" not in text
        assert "E:\\" not in text
