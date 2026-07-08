from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Expense
from app.services.time_service import now_utc


def _manual_report_expense(
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


def _insert_report_expense(
    *,
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
                tenant_id="owner",
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


def _create_starbucks_alias(client: TestClient, *, identity) -> None:
    alias = client.post(
        "/api/merchants/aliases",
        headers=identity.app_headers,
        json={"canonical_merchant": "星巴克", "alias": "STARBUCKS", "enabled": True},
    )
    assert alias.status_code == 201, alias.json()


def _seed_current_month_report_expenses(client: TestClient, *, identity) -> None:
    _manual_report_expense(
        client,
        headers=identity.app_headers,
        amount_cents=1200,
        merchant="STARBUCKS",
        category="餐饮",
        expense_time="2026-05-01T00:30:00Z",
    )
    _manual_report_expense(
        client,
        headers=identity.app_headers,
        amount_cents=800,
        merchant="星巴克",
        category="吃饭",
        expense_time="2026-05-02T00:30:00Z",
    )
    _manual_report_expense(
        client,
        headers=identity.app_headers,
        amount_cents=2200,
        merchant="地铁",
        category="交通",
        expense_time="2026-05-03T00:30:00Z",
    )
    _manual_report_expense(
        client,
        headers=identity.gray_app_headers,
        amount_cents=9999,
        merchant="灰度商家",
        category="餐饮",
        expense_time="2026-05-03T00:30:00Z",
    )


def _seed_comparison_report_expenses() -> None:
    _insert_report_expense(
        amount_cents=500,
        merchant="上月餐饮",
        category="吃饭",
        status="confirmed",
        expense_time=datetime(2026, 4, 10, 0, 0, tzinfo=UTC),
        confirmed_at=datetime(2026, 4, 10, 0, 1, tzinfo=UTC),
    )
    _insert_report_expense(
        amount_cents=1800,
        merchant="去年交通",
        category="交通",
        status="confirmed",
        expense_time=datetime(2025, 5, 11, 0, 0, tzinfo=UTC),
        confirmed_at=datetime(2025, 5, 11, 0, 1, tzinfo=UTC),
    )
    _insert_report_expense(
        amount_cents=700,
        merchant="去年日用品",
        category="日用品",
        status="confirmed",
        expense_time=datetime(2025, 5, 12, 0, 0, tzinfo=UTC),
        confirmed_at=datetime(2025, 5, 12, 0, 1, tzinfo=UTC),
    )
    _insert_report_expense(
        amount_cents=7777,
        merchant="待确认不应统计",
        category="餐饮",
        status="pending",
        expense_time=datetime(2026, 5, 4, 0, 0, tzinfo=UTC),
        confirmed_at=None,
    )


def seed_reports_overview_contract(client: TestClient, *, identity) -> None:
    _create_starbucks_alias(client, identity=identity)
    _seed_current_month_report_expenses(client, identity=identity)
    _seed_comparison_report_expenses()


def fetch_reports_overview_contract(client: TestClient, *, identity) -> dict:
    response = client.get(
        "/api/reports/overview?month=2026-05&timezone=UTC&granularity=day&top_n=5",
        headers=identity.app_headers,
    )
    assert response.status_code == 200, response.json()
    return response.json()


def assert_reports_overview_period_totals(payload: dict) -> None:
    assert payload["month"] == "2026-05"
    assert payload["timezone"] == "UTC"
    assert payload["granularity"] == "day"
    assert payload["total_amount_cents"] == 4200
    assert payload["count"] == 3
    assert payload["previous_month"] == "2026-04"
    assert payload["previous_total_amount_cents"] == 500
    assert payload["previous_count"] == 1
    assert payload["year_over_year_month"] == "2025-05"
    assert payload["year_over_year_total_amount_cents"] == 2500
    assert payload["year_over_year_count"] == 2
    assert payload["year_over_year_delta_amount_cents"] == 1700
    assert payload["year_over_year_delta_count"] == 1
    assert payload["merchant_category"] is None
    assert payload["ranking_metric"] == "amount"


def assert_reports_overview_trend_and_ranking(payload: dict) -> None:
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


def assert_reports_overview_category_comparison(payload: dict) -> None:
    assert payload["category_comparison"] == [
        {
            "category": "交通",
            "amount_cents": 2200,
            "count": 1,
            "previous_amount_cents": 0,
            "previous_count": 0,
            "delta_amount_cents": 2200,
            "delta_count": 1,
            "year_over_year_amount_cents": 1800,
            "year_over_year_count": 1,
            "year_over_year_delta_amount_cents": 400,
            "year_over_year_delta_count": 0,
        },
        {
            "category": "餐饮",
            "amount_cents": 2000,
            "count": 2,
            "previous_amount_cents": 500,
            "previous_count": 1,
            "delta_amount_cents": 1500,
            "delta_count": 1,
            "year_over_year_amount_cents": 0,
            "year_over_year_count": 0,
            "year_over_year_delta_amount_cents": 2000,
            "year_over_year_delta_count": 2,
        },
        {
            "category": "日用品",
            "amount_cents": 0,
            "count": 0,
            "previous_amount_cents": 0,
            "previous_count": 0,
            "delta_amount_cents": 0,
            "delta_count": 0,
            "year_over_year_amount_cents": 700,
            "year_over_year_count": 1,
            "year_over_year_delta_amount_cents": -700,
            "year_over_year_delta_count": -1,
        },
    ]
