"""v0.4-alpha3 Smart Ledger Engine — Rules preview/apply + Recurring candidates."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from api_contract_helpers import insert_confirmed_expense, upload_png
from app.database import SessionLocal
from app.models import Expense
from conftest import app_headers


# --- T17 Rules Preview ----------------------------------------------------


def _seed_pending_with_merchant(merchant: str) -> int:
    """Upload a PNG (pending), then patch its merchant to control matching."""
    # Use a TestClient implicitly via the fixture in the test that calls this helper.
    raise RuntimeError("call _patch_pending_merchant from a test using `client`")


def _set_pending_merchant(client: TestClient, expense_id: int, merchant: str) -> None:
    response = client.patch(
        f"/api/expenses/{expense_id}",
        headers=app_headers(),
        json={"merchant": merchant, "amount_cents": 3800},
    )
    assert response.status_code == 200


def test_rule_preview_does_not_modify(client: TestClient) -> None:
    first_id = upload_png(client)
    _set_pending_merchant(client, first_id, "STARBUCKS COFFEE")

    response = client.post(
        "/api/rules/preview",
        headers=app_headers(),
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


def test_rule_preview_rejects_empty_keyword(client: TestClient) -> None:
    response = client.post(
        "/api/rules/preview",
        headers=app_headers(),
        json={"keyword": "   ", "target_category": "餐饮"},
    )
    assert response.status_code == 422


def test_rule_preview_caps_items_by_limit(client: TestClient) -> None:
    ids: list[int] = []
    for index in range(3):
        new_id = upload_png(client)
        _set_pending_merchant(client, new_id, f"星巴克门店-{index}")
        ids.append(new_id)

    response = client.post(
        "/api/rules/preview",
        headers=app_headers(),
        json={"keyword": "星巴克", "target_category": "餐饮", "limit": 2},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["matched_count"] == 3
    assert len(body["items"]) == 2


# --- T18 Rules Apply Pending ---------------------------------------------


def test_rule_apply_pending_updates_category(client: TestClient) -> None:
    pending_id = upload_png(client)
    _set_pending_merchant(client, pending_id, "Starbucks 上海")

    # Seed a rule for Starbucks → 餐饮 with high priority.
    response = client.post(
        "/api/rules/categories",
        headers=app_headers(),
        json={"keyword": "Starbucks", "category": "餐饮", "enabled": True, "priority": 1},
    )
    assert response.status_code == 200

    response = client.post("/api/rules/apply-pending", headers=app_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["pending_scanned"] >= 1
    assert body["changed_count"] >= 1

    pending = client.get("/api/expenses/pending", headers=app_headers())
    assert pending.status_code == 200
    items = pending.json()
    target = next((item for item in items if int(item["id"]) == pending_id), None)
    assert target is not None
    assert target["category"] == "餐饮"
    assert target["status"] == "pending"  # NOT auto-confirmed


def test_rule_apply_pending_does_not_touch_confirmed(client: TestClient) -> None:
    confirmed_id = insert_confirmed_expense(
        amount_cents=4200,
        merchant="Starbucks 北京",
        category="其他",
        expense_time=datetime(2026, 5, 5, 12, 0, tzinfo=UTC),
        confirmed_at=datetime(2026, 5, 5, 12, 0, tzinfo=UTC),
    )
    client.post(
        "/api/rules/categories",
        headers=app_headers(),
        json={"keyword": "Starbucks", "category": "餐饮", "enabled": True, "priority": 1},
    )

    response = client.post("/api/rules/apply-pending", headers=app_headers())
    assert response.status_code == 200

    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.id == confirmed_id))
        assert expense is not None
        # Confirmed records are never re-classified by apply-pending.
        assert expense.category == "其他"
        assert expense.status == "confirmed"


def test_rule_apply_pending_does_not_auto_confirm(client: TestClient) -> None:
    pending_id = upload_png(client)
    _set_pending_merchant(client, pending_id, "Kimi 订阅")
    client.post(
        "/api/rules/categories",
        headers=app_headers(),
        json={"keyword": "Kimi", "category": "AI订阅", "enabled": True, "priority": 1},
    )

    response = client.post("/api/rules/apply-pending", headers=app_headers())
    assert response.status_code == 200

    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.id == pending_id))
        assert expense is not None
        assert expense.status == "pending"


def test_rule_apply_pending_skips_non_default_category(client: TestClient) -> None:
    pending_id = upload_png(client)
    # Already classified as 交通 — apply-pending must respect user choice.
    response = client.patch(
        f"/api/expenses/{pending_id}",
        headers=app_headers(),
        json={"merchant": "Starbucks", "category": "交通", "amount_cents": 1000},
    )
    assert response.status_code == 200
    client.post(
        "/api/rules/categories",
        headers=app_headers(),
        json={"keyword": "Starbucks", "category": "餐饮", "enabled": True, "priority": 1},
    )

    response = client.post("/api/rules/apply-pending", headers=app_headers())
    assert response.status_code == 200

    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.id == pending_id))
        assert expense is not None
        assert expense.category == "交通"


# --- T24 Recurring candidates --------------------------------------------


def test_recurring_candidates_empty(client: TestClient) -> None:
    response = client.get("/api/insights/recurring-candidates", headers=app_headers())
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_recurring_candidates_detects_monthly_merchant(client: TestClient) -> None:
    # 3 months of ChatGPT subscription, amounts within 15%.
    base = datetime(2026, 5, 5, 12, 0, tzinfo=UTC)
    for month_offset, amount in [(2, 20000), (1, 20000), (0, 20800)]:
        when = base - timedelta(days=30 * month_offset)
        insert_confirmed_expense(
            amount_cents=amount,
            merchant="ChatGPT Plus",
            category="AI订阅",
            expense_time=when,
            confirmed_at=when,
        )
    response = client.get("/api/insights/recurring-candidates", headers=app_headers())
    assert response.status_code == 200
    items = response.json()["items"]
    chatgpt = next((item for item in items if "ChatGPT" in item["merchant"]), None)
    assert chatgpt is not None
    assert chatgpt["occurrence_count"] >= 2
    assert chatgpt["confidence"] in {"medium", "high"}
    assert chatgpt["amount_cents"] > 0


def test_recurring_candidates_ignores_one_off(client: TestClient) -> None:
    when = datetime(2026, 5, 5, 12, 0, tzinfo=UTC)
    insert_confirmed_expense(
        amount_cents=99900,
        merchant="一次性家电",
        category="其他",
        expense_time=when,
        confirmed_at=when,
    )
    response = client.get("/api/insights/recurring-candidates", headers=app_headers())
    assert response.status_code == 200
    items = response.json()["items"]
    assert all("一次性家电" not in item["merchant"] for item in items)


def test_recurring_candidates_ignores_amount_drift(client: TestClient) -> None:
    # Same merchant 3 months but amounts way off → excluded.
    base = datetime(2026, 5, 5, 12, 0, tzinfo=UTC)
    for month_offset, amount in [(2, 5000), (1, 30000), (0, 18000)]:
        when = base - timedelta(days=30 * month_offset)
        insert_confirmed_expense(
            amount_cents=amount,
            merchant="水电费",
            category="住房",
            expense_time=when,
            confirmed_at=when,
        )
    response = client.get("/api/insights/recurring-candidates", headers=app_headers())
    assert response.status_code == 200
    items = response.json()["items"]
    assert all("水电费" not in item["merchant"] for item in items)


# --- No-secret-leak smoke -------------------------------------------------


def test_alpha3_endpoints_no_secret_leak(client: TestClient) -> None:
    upload_png(client)
    for path, method, body in [
        ("/api/rules/preview", "POST", {"keyword": "x", "target_category": "餐饮"}),
        ("/api/rules/apply-pending", "POST", None),
        ("/api/insights/recurring-candidates", "GET", None),
    ]:
        if method == "GET":
            response = client.get(path, headers=app_headers())
        else:
            response = client.post(path, headers=app_headers(), json=body)
        assert response.status_code == 200
        text = response.text
        assert "token_hash" not in text
        assert "upload_key" not in text
        assert "E:\\" not in text
