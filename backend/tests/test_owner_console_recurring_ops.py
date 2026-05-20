"""Owner Console recurring and notification draft service-status card."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import RecurringItem
from app.routes.owner_console import _require_local
from app.services.time_service import now_utc


@pytest.fixture()
def local_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_require_local, None)


def test_owner_index_renders_recurring_ops_status(local_client: TestClient, *, identity) -> None:
    today = now_utc().date()
    with SessionLocal() as db:
        db.add_all(
            [
                RecurringItem(
                    tenant_id="owner",
                    merchant_key="chatgpt plus",
                    merchant_name="ChatGPT Plus",
                    frequency="monthly",
                    baseline_amount_cents=20000,
                    last_amount_cents=20000,
                    occurrence_count=3,
                    next_expected_date=today + timedelta(days=1),
                    status="active",
                    confidence="high",
                    source="candidate",
                ),
                RecurringItem(
                    tenant_id="owner",
                    merchant_key="spotify",
                    merchant_name="Spotify",
                    frequency="monthly",
                    baseline_amount_cents=1800,
                    last_amount_cents=1800,
                    occurrence_count=2,
                    next_expected_date=today - timedelta(days=1),
                    status="paused",
                    confidence="medium",
                    source="candidate",
                ),
                RecurringItem(
                    tenant_id="owner",
                    merchant_key="old service",
                    merchant_name="Old Service",
                    frequency="monthly",
                    baseline_amount_cents=900,
                    last_amount_cents=900,
                    occurrence_count=2,
                    next_expected_date=today - timedelta(days=10),
                    status="archived",
                    confidence="low",
                    source="candidate",
                ),
            ]
        )
        db.commit()

    first = local_client.post(
        "/api/expenses/notification-drafts",
        headers=identity.app_headers,
        json={
            "source": "wechat",
            "amount_cents": 2580,
            "merchant": "星巴克",
            "expense_time": now_utc().isoformat(),
        },
    )
    assert first.status_code == 200
    second = local_client.post(
        "/api/expenses/notification-drafts",
        headers=identity.app_headers,
        json={
            "source": "alipay",
            "amount_cents": 1234,
            "expense_time": now_utc().isoformat(),
        },
    )
    assert second.status_code == 200

    body = local_client.get("/owner").text
    assert "Recurring / 通知草稿状态" in body
    assert "固定支出活跃" in body
    assert "通知草稿待确认" in body
    assert "草稿缺字段" in body
    assert "近 24 小时通知草稿：2" in body
    assert "已归档固定支出：1" in body
    assert "/web/recurring?ledger_id=owner" in body
