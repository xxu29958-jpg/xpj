"""v0.4-alpha3 Smart Ledger Engine — Rules preview/apply + Recurring candidates."""
from __future__ import annotations

import json
from datetime import UTC, datetime

from api_contract_helpers import insert_confirmed_expense, patch_expense, upload_png
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Expense


def _seed_pending_with_merchant(merchant: str) -> int:
    """Upload a PNG (pending), then patch its merchant to control matching."""
    # Use a TestClient implicitly via the fixture in the test that calls this helper.
    raise RuntimeError("call _patch_pending_merchant from a test using `client`")


def _set_pending_merchant(client: TestClient, expense_id: int, merchant: str, *, identity) -> None:
    response = patch_expense(
        client,
        expense_id,
        headers=identity.app_headers,
        fields={"merchant": merchant, "amount_cents": 3800},
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


def test_rule_apply_pending_preview_does_not_modify_and_reports_scope(
    client: TestClient, *, identity,
) -> None:
    default_id = upload_png(client, identity=identity)
    _set_pending_merchant(client, default_id, "Starbucks 上海", identity=identity)
    custom_id = upload_png(client, identity=identity)
    custom = patch_expense(
        client,
        custom_id,
        headers=identity.app_headers,
        fields={"merchant": "Starbucks 手动分类", "category": "交通", "amount_cents": 1000},
    )
    assert custom.status_code == 200

    response = client.post(
        "/api/rules/categories",
        headers=identity.app_headers,
        json={"keyword": "Starbucks", "category": "餐饮", "enabled": True, "priority": 1},
    )
    assert response.status_code == 200

    preview = client.post(
        "/api/rules/apply-pending/preview?limit=10",
        headers=identity.app_headers,
    )
    assert preview.status_code == 200
    body = preview.json()
    assert body["pending_scanned"] == 1
    assert body["changed_count"] == 1
    assert body["skipped_non_default_category"] == 1
    assert body["conflict_count"] == 0
    assert body["preview_token"]
    assert body["items"] == [
        {
            "id": default_id,
            "merchant": "Starbucks 上海",
            "current_category": "其他",
            "suggested_category": "餐饮",
            "rule_keyword": "Starbucks",
            "reason": "规则[Starbucks] 将分类改为 餐饮",
        }
    ]

    with SessionLocal() as db:
        default = db.scalar(select(Expense).where(Expense.id == default_id))
        custom_expense = db.scalar(select(Expense).where(Expense.id == custom_id))
        assert default is not None
        assert custom_expense is not None
        assert default.category == "其他"
        assert custom_expense.category == "交通"


def test_rule_apply_pending_updates_category(client: TestClient, *, identity) -> None:
    pending_id = upload_png(client, identity=identity)
    with SessionLocal() as db:
        expense = db.get(Expense, pending_id)
        assert expense is not None
        expense.ocr_draft_fields = json.dumps(["category", "merchant"])
        db.commit()
    _set_pending_merchant(client, pending_id, "Starbucks 上海", identity=identity)

    # Seed a rule for Starbucks → 餐饮 with high priority.
    response = client.post(
        "/api/rules/categories",
        headers=identity.app_headers,
        json={"keyword": "Starbucks", "category": "餐饮", "enabled": True, "priority": 1},
    )
    assert response.status_code == 200

    response = _apply_pending_rules(client, identity=identity)
    assert response.status_code == 200
    body = response.json()
    assert body["pending_scanned"] >= 1
    assert body["changed_count"] >= 1

    pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    assert pending.status_code == 200
    items = pending.json()
    target = next((item for item in items if int(item["id"]) == pending_id), None)
    assert target is not None
    with SessionLocal() as db:
        expense = db.get(Expense, pending_id)
        assert expense is not None
        assert set(json.loads(expense.ocr_draft_fields or "[]")) == set()
    assert target["category"] == "餐饮"
    assert target["status"] == "pending"  # NOT auto-confirmed


def test_rule_apply_pending_requires_fresh_preview_token(client: TestClient, *, identity) -> None:
    pending_id = upload_png(client, identity=identity)
    _set_pending_merchant(client, pending_id, "PendingPreviewCafe", identity=identity)
    created = client.post(
        "/api/rules/categories",
        headers=identity.app_headers,
        json={"keyword": "PendingPreviewCafe", "category": "椁愰ギ", "enabled": True, "priority": 1},
    )
    assert created.status_code == 200
    rule_id = created.json()["id"]

    missing = client.post(
        "/api/rules/apply-pending",
        headers=identity.app_headers,
        json={"confirm": True},
    )
    assert missing.status_code == 409
    assert missing.json()["error"] == "preview_required"

    preview = client.post("/api/rules/apply-pending/preview", headers=identity.app_headers)
    assert preview.status_code == 200
    token = preview.json()["preview_token"]

    changed_rule = client.patch(
        f"/api/rules/categories/{rule_id}",
        headers=identity.app_headers,
        json={
            "category": "Transport",
            "expected_updated_at": created.json()["updated_at"],
        },
    )
    assert changed_rule.status_code == 200
    stale = client.post(
        "/api/rules/apply-pending",
        headers=identity.app_headers,
        json={"confirm": True, "preview_token": token},
    )
    assert stale.status_code == 409
    assert stale.json()["error"] == "preview_stale"
    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.id == pending_id))
        assert expense is not None
        assert expense.category != "Transport"


def test_rule_apply_pending_does_not_touch_confirmed(client: TestClient, *, identity) -> None:
    confirmed_id = insert_confirmed_expense(
        amount_cents=4200,
        merchant="Starbucks 北京",
        category="其他",
        expense_time=datetime(2026, 5, 5, 12, 0, tzinfo=UTC),
        confirmed_at=datetime(2026, 5, 5, 12, 0, tzinfo=UTC),
    )
    client.post(
        "/api/rules/categories",
        headers=identity.app_headers,
        json={"keyword": "Starbucks", "category": "餐饮", "enabled": True, "priority": 1},
    )

    response = _apply_pending_rules(client, identity=identity)
    assert response.status_code == 200

    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.id == confirmed_id))
        assert expense is not None
        # Confirmed records are never re-classified by apply-pending.
        assert expense.category == "其他"
        assert expense.status == "confirmed"


def test_rule_apply_pending_does_not_auto_confirm(client: TestClient, *, identity) -> None:
    pending_id = upload_png(client, identity=identity)
    _set_pending_merchant(client, pending_id, "Kimi 订阅", identity=identity)
    client.post(
        "/api/rules/categories",
        headers=identity.app_headers,
        json={"keyword": "Kimi", "category": "AI订阅", "enabled": True, "priority": 1},
    )

    response = _apply_pending_rules(client, identity=identity)
    assert response.status_code == 200

    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.id == pending_id))
        assert expense is not None
        assert expense.status == "pending"


def test_rule_apply_pending_skips_non_default_category(client: TestClient, *, identity) -> None:
    pending_id = upload_png(client, identity=identity)
    # Already classified as 交通 — apply-pending must respect user choice.
    response = patch_expense(
        client,
        pending_id,
        headers=identity.app_headers,
        fields={"merchant": "Starbucks", "category": "交通", "amount_cents": 1000},
    )
    assert response.status_code == 200
    client.post(
        "/api/rules/categories",
        headers=identity.app_headers,
        json={"keyword": "Starbucks", "category": "餐饮", "enabled": True, "priority": 1},
    )

    response = _apply_pending_rules(client, identity=identity)
    assert response.status_code == 200

    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.id == pending_id))
        assert expense is not None
        assert expense.category == "交通"
