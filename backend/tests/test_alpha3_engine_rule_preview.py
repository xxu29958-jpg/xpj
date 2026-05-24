"""v0.4-alpha3 Smart Ledger Engine — Rules preview/apply + Recurring candidates."""
from __future__ import annotations

from api_contract_helpers import upload_png
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import CategoryRule, Expense


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


def test_rule_preview_does_not_modify(client: TestClient, *, identity) -> None:
    first_id = upload_png(client, identity=identity)
    _set_pending_merchant(client, first_id, "STARBUCKS COFFEE", identity=identity)

    response = client.post(
        "/api/rules/preview",
        headers=identity.app_headers,
        json={
            "keyword": "STARBUCKS",
            "target_category": "餐饮",
            "match_field": "merchant",
            "limit": 10,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["matched_count"] >= 1
    assert len(body["items"]) >= 1
    first = body["items"][0]
    assert first["merchant"] == "STARBUCKS COFFEE"
    assert first["suggested_category"] == "餐饮"
    assert "STARBUCKS" in first["reason"]

    # Database not mutated.
    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.id == first_id))
        assert expense is not None
        # Original category remains "其他" because we never applied.
        assert expense.category == "其他"


def test_rule_preview_rejects_empty_keyword(client: TestClient, *, identity) -> None:
    response = client.post(
        "/api/rules/preview",
        headers=identity.app_headers,
        json={"keyword": "   ", "target_category": "餐饮"},
    )
    assert response.status_code == 422


def test_rule_preview_caps_items_by_limit(client: TestClient, *, identity) -> None:
    ids: list[int] = []
    for index in range(3):
        new_id = upload_png(client, identity=identity)
        _set_pending_merchant(client, new_id, f"星巴克门店-{index}", identity=identity)
        ids.append(new_id)

    response = client.post(
        "/api/rules/preview",
        headers=identity.app_headers,
        json={"keyword": "星巴克", "target_category": "餐饮", "limit": 2},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["matched_count"] == 3
    assert len(body["items"]) == 2


def test_rule_patch_can_clear_optional_filters(client: TestClient, *, identity) -> None:
    created = client.post(
        "/api/rules/categories",
        headers=identity.app_headers,
        json={
            "keyword": "Coffee",
            "category": "餐饮",
            "enabled": True,
            "priority": 9,
            "amount_min_cents": 100,
            "amount_max_cents": 9999,
            "source_contains": "alipay",
            "tag_contains": "work",
        },
    )
    assert created.status_code == 200, created.json()
    rule_id = created.json()["id"]

    patched = client.patch(
        f"/api/rules/categories/{rule_id}",
        headers=identity.app_headers,
        json={
            "amount_min_cents": None,
            "amount_max_cents": None,
            "source_contains": None,
            "tag_contains": None,
        },
    )

    assert patched.status_code == 200, patched.json()
    body = patched.json()
    assert body["amount_min_cents"] is None
    assert body["amount_max_cents"] is None
    assert body["source_contains"] is None
    assert body["tag_contains"] is None
    with SessionLocal() as db:
        rule = db.scalar(select(CategoryRule).where(CategoryRule.id == rule_id))
        assert rule is not None
        assert rule.amount_min_cents is None
        assert rule.amount_max_cents is None
        assert rule.source_contains is None
        assert rule.tag_contains is None
