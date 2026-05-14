from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Expense, LedgerMember
from app.services.time_service import now_utc
from conftest import app_headers, gray_app_headers


def _manual_expense(
    client: TestClient,
    *,
    headers: dict[str, str],
    amount_cents: int,
    merchant: str,
    category: str,
    expense_time: str,
) -> None:
    response = client.post(
        "/api/expenses/manual",
        headers=headers,
        json={
            "amount_cents": amount_cents,
            "merchant": merchant,
            "category": category,
            "expense_time": expense_time,
        },
    )
    assert response.status_code == 200, response.json()


def _insert_expense(
    *,
    tenant_id: str = "owner",
    amount_cents: int,
    merchant: str,
    category: str,
    status: str,
    expense_time: datetime | None,
    confirmed_at: datetime | None,
) -> None:
    now = now_utc()
    with SessionLocal() as db:
        db.add(
            Expense(
                tenant_id=tenant_id,
                amount_cents=amount_cents,
                merchant=merchant,
                category=category,
                note="",
                source="pytest",
                status=status,
                expense_time=expense_time,
                created_at=confirmed_at or now,
                updated_at=confirmed_at or now,
                confirmed_at=confirmed_at,
            )
        )
        db.commit()


def _set_owner_ledger_role(role: str) -> None:
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1))
        assert member is not None
        member.role = role
        db.commit()


def test_reports_overview_trends_rankings_and_category_comparison(
    client: TestClient,
) -> None:
    alias = client.post(
        "/api/merchants/aliases",
        headers=app_headers(),
        json={"canonical_merchant": "星巴克", "alias": "STARBUCKS", "enabled": True},
    )
    assert alias.status_code == 201, alias.json()

    _manual_expense(
        client,
        headers=app_headers(),
        amount_cents=1200,
        merchant="STARBUCKS",
        category="餐饮",
        expense_time="2026-05-01T00:30:00Z",
    )
    _manual_expense(
        client,
        headers=app_headers(),
        amount_cents=800,
        merchant="星巴克",
        category="吃饭",
        expense_time="2026-05-02T00:30:00Z",
    )
    _manual_expense(
        client,
        headers=app_headers(),
        amount_cents=2200,
        merchant="地铁",
        category="交通",
        expense_time="2026-05-03T00:30:00Z",
    )
    _manual_expense(
        client,
        headers=gray_app_headers(),
        amount_cents=9999,
        merchant="灰度商家",
        category="餐饮",
        expense_time="2026-05-03T00:30:00Z",
    )
    _insert_expense(
        amount_cents=500,
        merchant="上月餐饮",
        category="吃饭",
        status="confirmed",
        expense_time=datetime(2026, 4, 10, 0, 0, tzinfo=UTC),
        confirmed_at=datetime(2026, 4, 10, 0, 1, tzinfo=UTC),
    )
    _insert_expense(
        amount_cents=7777,
        merchant="待确认不应统计",
        category="餐饮",
        status="pending",
        expense_time=datetime(2026, 5, 4, 0, 0, tzinfo=UTC),
        confirmed_at=None,
    )

    response = client.get(
        "/api/reports/overview?month=2026-05&timezone=UTC&granularity=day&top_n=5",
        headers=app_headers(),
    )
    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["month"] == "2026-05"
    assert payload["timezone"] == "UTC"
    assert payload["granularity"] == "day"
    assert payload["total_amount_cents"] == 4200
    assert payload["count"] == 3
    assert payload["previous_month"] == "2026-04"
    assert payload["previous_total_amount_cents"] == 500
    assert payload["previous_count"] == 1
    assert payload["merchant_category"] is None
    assert payload["ranking_metric"] == "amount"
    assert payload["trend"][0] == {
        "bucket": "2026-05-01",
        "label": "05-01",
        "amount_cents": 1200,
        "count": 1,
    }
    assert len(payload["trend"]) == 31
    assert payload["merchant_ranking"] == [
        {"merchant": "地铁", "amount_cents": 2200, "count": 1},
        {"merchant": "星巴克", "amount_cents": 2000, "count": 2},
    ]
    assert "灰度商家" not in str(payload)
    assert payload["category_comparison"] == [
        {
            "category": "交通",
            "amount_cents": 2200,
            "count": 1,
            "previous_amount_cents": 0,
            "previous_count": 0,
            "delta_amount_cents": 2200,
            "delta_count": 1,
        },
        {
            "category": "餐饮",
            "amount_cents": 2000,
            "count": 2,
            "previous_amount_cents": 500,
            "previous_count": 1,
            "delta_amount_cents": 1500,
            "delta_count": 1,
        },
    ]


def test_reports_merchant_ranking_category_metric_and_csv_export(
    client: TestClient,
) -> None:
    for _ in range(3):
        _manual_expense(
            client,
            headers=app_headers(),
            amount_cents=100,
            merchant="A店",
            category="餐饮",
            expense_time="2026-05-02T00:30:00Z",
        )
    _manual_expense(
        client,
        headers=app_headers(),
        amount_cents=1000,
        merchant="B店",
        category="吃饭",
        expense_time="2026-05-03T00:30:00Z",
    )
    _manual_expense(
        client,
        headers=app_headers(),
        amount_cents=2000,
        merchant="交通店",
        category="交通",
        expense_time="2026-05-03T00:30:00Z",
    )

    response = client.get(
        "/api/reports/overview?"
        "month=2026-05&timezone=UTC&merchant_category=吃饭&ranking_metric=count&top_n=2",
        headers=app_headers(),
    )
    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["total_amount_cents"] == 3300
    assert payload["merchant_category"] == "餐饮"
    assert payload["ranking_metric"] == "count"
    assert payload["merchant_ranking"] == [
        {"merchant": "A店", "amount_cents": 300, "count": 3},
        {"merchant": "B店", "amount_cents": 1000, "count": 1},
    ]
    assert "交通店" not in str(payload["merchant_ranking"])

    _set_owner_ledger_role("viewer")
    csv_response = client.get(
        "/api/reports/overview.csv?"
        "month=2026-05&timezone=UTC&granularity=week&merchant_category=餐饮"
        "&ranking_metric=count&top_n=1",
        headers=app_headers(),
    )
    assert csv_response.status_code == 200, csv_response.text
    assert csv_response.headers["content-type"].startswith("text/csv")
    assert "ticketbox-reports-overview-2026-05-week.csv" in csv_response.headers[
        "content-disposition"
    ]
    assert csv_response.text.startswith("\ufeffsection,field,value")
    assert "summary,ranking_metric,count" in csv_response.text
    assert "merchant_ranking,1,A店,300,3" in csv_response.text
    assert "category_comparison,交通,2000,1" in csv_response.text


def test_reports_overview_uses_timezone_and_confirmed_at_fallback(
    client: TestClient,
) -> None:
    _insert_expense(
        amount_cents=1851,
        merchant="手机时区边界账单",
        category="生活",
        status="confirmed",
        expense_time=None,
        confirmed_at=datetime(2026, 4, 30, 16, 30, tzinfo=UTC),
    )

    shanghai = client.get(
        "/api/reports/overview?month=2026-05&timezone=Asia/Shanghai&granularity=day",
        headers=app_headers(),
    )
    assert shanghai.status_code == 200, shanghai.json()
    shanghai_payload = shanghai.json()
    assert shanghai_payload["total_amount_cents"] == 1851
    assert shanghai_payload["trend"][0] == {
        "bucket": "2026-05-01",
        "label": "05-01",
        "amount_cents": 1851,
        "count": 1,
    }

    utc_may = client.get(
        "/api/reports/overview?month=2026-05&timezone=UTC", headers=app_headers()
    )
    assert utc_may.status_code == 200, utc_may.json()
    assert utc_may.json()["total_amount_cents"] == 0

    utc_april = client.get(
        "/api/reports/overview?month=2026-04&timezone=UTC&granularity=week",
        headers=app_headers(),
    )
    assert utc_april.status_code == 200, utc_april.json()
    assert utc_april.json()["total_amount_cents"] == 1851
    assert any(point["amount_cents"] == 1851 for point in utc_april.json()["trend"])


def test_reports_overview_month_granularity_and_viewer_read(
    client: TestClient,
) -> None:
    _manual_expense(
        client,
        headers=app_headers(),
        amount_cents=1000,
        merchant="一月",
        category="生活",
        expense_time="2026-01-03T00:00:00Z",
    )
    _manual_expense(
        client,
        headers=app_headers(),
        amount_cents=5000,
        merchant="五月",
        category="生活",
        expense_time="2026-05-03T00:00:00Z",
    )
    _set_owner_ledger_role("viewer")

    response = client.get(
        "/api/reports/overview?month=2026-05&timezone=UTC&granularity=month",
        headers=app_headers(),
    )
    assert response.status_code == 200, response.json()
    payload = response.json()
    assert [point["bucket"] for point in payload["trend"]] == [
        "2025-12",
        "2026-01",
        "2026-02",
        "2026-03",
        "2026-04",
        "2026-05",
    ]
    assert payload["trend"][1]["amount_cents"] == 1000
    assert payload["trend"][-1]["amount_cents"] == 5000


def test_reports_overview_invalid_month_and_empty_data(client: TestClient) -> None:
    invalid = client.get(
        "/api/reports/overview?month=2026-13", headers=app_headers()
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"] == "invalid_request"

    empty = client.get(
        "/api/reports/overview?month=2026-06&timezone=UTC", headers=app_headers()
    )
    assert empty.status_code == 200, empty.json()
    payload = empty.json()
    assert payload["total_amount_cents"] == 0
    assert payload["count"] == 0
    assert payload["merchant_ranking"] == []
    assert payload["category_comparison"] == []
    assert len(payload["trend"]) == 30
