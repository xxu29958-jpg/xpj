"""v0.4-alpha3 Smart Ledger Engine — Rules preview/apply + Recurring candidates."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from api_contract_helpers import insert_confirmed_expense, upload_png
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import CategoryRule, Expense, LedgerMember, RuleApplicationBatch, RuleApplicationChange
from app.services.rule_application_service import _try_apply_rule_category, _try_rollback_rule_change
from app.services.time_service import now_utc


def _seed_pending_with_merchant(merchant: str) -> int:
    """Upload a PNG (pending), then patch its merchant to control matching."""
    # Use a TestClient implicitly via the fixture in the test that calls this helper.
    raise RuntimeError("call _patch_pending_merchant from a test using `client`")


def _set_pending_merchant(client: TestClient, expense_id: int, merchant: str, *, identity) -> None:
    response = client.patch(
        f"/api/expenses/{expense_id}",
        headers=identity.app_headers,
        json={"merchant": merchant, "amount_cents": 3800},
    )
    assert response.status_code == 200


def _apply_pending_rules(client: TestClient, *, identity, max_scan: int = 500):
    preview = client.post(
        f"/api/rules/apply-pending/preview?max_scan={max_scan}",
        headers=identity.app_headers,
    )
    assert preview.status_code == 200, preview.json()
    token = preview.json()["preview_token"]
    return client.post(
        f"/api/rules/apply-pending?max_scan={max_scan}",
        headers=identity.app_headers,
        json={"confirm": True, "preview_token": token},
    )


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
            response = client.post(path, headers=identity.app_headers, json=body)
        assert response.status_code == 200
        text = response.text
        assert "token_hash" not in text
        assert "upload_key" not in text
        assert "E:\\" not in text
