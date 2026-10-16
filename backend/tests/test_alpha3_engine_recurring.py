"""v0.4-alpha3 Smart Ledger Engine — Rules preview/apply + Recurring candidates."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from api_contract_helpers import insert_confirmed_expense
from fastapi.testclient import TestClient


def test_recurring_candidates_empty(client: TestClient, *, identity) -> None:
    response = client.get("/api/insights/recurring-candidates", headers=identity.app_headers)
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_recurring_candidates_detects_monthly_merchant(client: TestClient, *, identity) -> None:
    # 3 months of ChatGPT subscription, amounts within 15%.
    # PR #253 R4: 候选扫描窗口为近 6 个月, 播种改相对日期 (固定日期会随时间掉出窗口)。
    base = datetime.now(UTC) - timedelta(days=2)
    for month_offset, amount in [(2, 20000), (1, 20000), (0, 20800)]:
        when = base - timedelta(days=30 * month_offset)
        insert_confirmed_expense(
            amount_cents=amount,
            merchant="ChatGPT Plus",
            category="AI订阅",
            expense_time=when,
            confirmed_at=when,
        )
    response = client.get("/api/insights/recurring-candidates", headers=identity.app_headers)
    assert response.status_code == 200
    items = response.json()["items"]
    chatgpt = next((item for item in items if "ChatGPT" in item["merchant"]), None)
    assert chatgpt is not None
    assert chatgpt["occurrence_count"] >= 2
    assert chatgpt["confidence"] in {"medium", "high"}
    assert chatgpt["amount_cents"] > 0


def test_recurring_candidates_ignores_one_off(client: TestClient, *, identity) -> None:
    when = datetime.now(UTC) - timedelta(days=2)
    insert_confirmed_expense(
        amount_cents=99900,
        merchant="一次性家电",
        category="其他",
        expense_time=when,
        confirmed_at=when,
    )
    response = client.get("/api/insights/recurring-candidates", headers=identity.app_headers)
    assert response.status_code == 200
    items = response.json()["items"]
    assert all("一次性家电" not in item["merchant"] for item in items)


def test_recurring_candidates_ignores_amount_drift(client: TestClient, *, identity) -> None:
    # Same merchant 3 months but amounts way off → excluded.
    base = datetime.now(UTC) - timedelta(days=2)
    for month_offset, amount in [(2, 5000), (1, 30000), (0, 18000)]:
        when = base - timedelta(days=30 * month_offset)
        insert_confirmed_expense(
            amount_cents=amount,
            merchant="水电费",
            category="住房",
            expense_time=when,
            confirmed_at=when,
        )
    response = client.get("/api/insights/recurring-candidates", headers=identity.app_headers)
    assert response.status_code == 200
    items = response.json()["items"]
    assert all("水电费" not in item["merchant"] for item in items)
