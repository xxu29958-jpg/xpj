from __future__ import annotations

import csv
from datetime import UTC, datetime
from io import StringIO

from fastapi.testclient import TestClient

from api_contract_helpers import (
    insert_confirmed_expense,
)
from app.database import SessionLocal
from app.models import Expense
from app.services import web_stats_service
from conftest import (
    app_headers,
)


def test_local_timezone_month_filter_matches_android_display_month(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/expenses/manual",
        headers=app_headers(),
        json={
            "amount_cents": 1851,
            "merchant": "跨月边界账单",
            "category": "生活",
            "expense_time": "2026-04-30T16:30:00Z",
        },
    )
    assert response.status_code == 200

    may_page = client.get(
        "/api/expenses/confirmed?month=2026-05", headers=app_headers()
    )
    assert may_page.status_code == 200
    assert may_page.json()["total"] == 1

    april_page = client.get(
        "/api/expenses/confirmed?month=2026-04", headers=app_headers()
    )
    assert april_page.status_code == 200
    assert april_page.json()["total"] == 0

    may_stats = client.get("/api/stats/monthly?month=2026-05", headers=app_headers())
    assert may_stats.status_code == 200
    assert may_stats.json()["total_amount_cents"] == 1851

    april_stats = client.get("/api/stats/monthly?month=2026-04", headers=app_headers())
    assert april_stats.status_code == 200
    assert april_stats.json()["total_amount_cents"] == 0

    months = client.get("/api/expenses/months", headers=app_headers())
    assert months.status_code == 200
    assert months.json()["items"] == ["2026-05"]


def test_web_stats_day_grouping_uses_configured_local_timezone(
    client: TestClient,
) -> None:
    del client
    insert_confirmed_expense(
        amount_cents=1851,
        merchant="Web 跨日账单",
        category="生活",
        expense_time=datetime(2026, 4, 30, 16, 30, tzinfo=UTC),
        confirmed_at=datetime(2026, 4, 30, 16, 31, tzinfo=UTC),
    )

    with SessionLocal() as db:
        may_days = web_stats_service.confirmed_by_day(db, "owner", "2026-05")
        april_days = web_stats_service.confirmed_by_day(db, "owner", "2026-04")

    assert may_days == [
        {
            "date": "2026-05-01",
            "amount_cents": 1851,
            "amount_yuan": 18.51,
            "count": 1,
        }
    ]
    assert april_days == []


def test_confirmed_month_filter_falls_back_to_confirmed_at_and_category(
    client: TestClient,
) -> None:
    insert_confirmed_expense(
        amount_cents=501,
        merchant="确认时间跨月餐饮",
        category="餐饮",
        expense_time=None,
        confirmed_at=datetime(2026, 4, 30, 16, 30, tzinfo=UTC),
    )
    insert_confirmed_expense(
        amount_cents=777,
        merchant="确认时间上月餐饮",
        category="餐饮",
        expense_time=None,
        confirmed_at=datetime(2026, 4, 30, 15, 30, tzinfo=UTC),
    )
    insert_confirmed_expense(
        amount_cents=888,
        merchant="确认时间跨月交通",
        category="交通",
        expense_time=None,
        confirmed_at=datetime(2026, 4, 30, 16, 40, tzinfo=UTC),
    )

    may_food_page = client.get(
        "/api/expenses/confirmed?month=2026-05&category=餐饮", headers=app_headers()
    )
    assert may_food_page.status_code == 200
    may_food_payload = may_food_page.json()
    assert may_food_payload["total"] == 1
    assert may_food_payload["items"][0]["merchant"] == "确认时间跨月餐饮"

    april_food_page = client.get(
        "/api/expenses/confirmed?month=2026-04&category=餐饮", headers=app_headers()
    )
    assert april_food_page.status_code == 200
    april_food_payload = april_food_page.json()
    assert april_food_payload["total"] == 1
    assert april_food_payload["items"][0]["merchant"] == "确认时间上月餐饮"

    may_stats = client.get("/api/stats/monthly?month=2026-05", headers=app_headers())
    assert may_stats.status_code == 200
    may_stats_payload = may_stats.json()
    assert may_stats_payload["total_amount_cents"] == 1389
    assert may_stats_payload["count"] == 2
    assert may_stats_payload["by_category"] == [
        {"category": "交通", "amount_cents": 888, "count": 1},
        {"category": "餐饮", "amount_cents": 501, "count": 1},
    ]

    april_stats = client.get("/api/stats/monthly?month=2026-04", headers=app_headers())
    assert april_stats.status_code == 200
    assert april_stats.json()["total_amount_cents"] == 777

    months = client.get("/api/expenses/months", headers=app_headers())
    assert months.status_code == 200
    assert months.json()["items"] == ["2026-05", "2026-04"]


def test_confirmed_month_filter_handles_cross_year_local_boundary(
    client: TestClient,
) -> None:
    insert_confirmed_expense(
        amount_cents=1234,
        merchant="跨年后餐饮",
        category="餐饮",
        expense_time=datetime(2026, 12, 31, 16, 30, tzinfo=UTC),
        confirmed_at=datetime(2026, 12, 31, 16, 31, tzinfo=UTC),
    )
    insert_confirmed_expense(
        amount_cents=4321,
        merchant="跨年前餐饮",
        category="餐饮",
        expense_time=datetime(2026, 12, 31, 15, 30, tzinfo=UTC),
        confirmed_at=datetime(2026, 12, 31, 15, 31, tzinfo=UTC),
    )

    january_page = client.get(
        "/api/expenses/confirmed?month=2027-01&category=餐饮", headers=app_headers()
    )
    assert january_page.status_code == 200
    january_payload = january_page.json()
    assert january_payload["total"] == 1
    assert january_payload["items"][0]["merchant"] == "跨年后餐饮"

    december_page = client.get(
        "/api/expenses/confirmed?month=2026-12&category=餐饮", headers=app_headers()
    )
    assert december_page.status_code == 200
    december_payload = december_page.json()
    assert december_payload["total"] == 1
    assert december_payload["items"][0]["merchant"] == "跨年前餐饮"

    january_stats = client.get(
        "/api/stats/monthly?month=2027-01", headers=app_headers()
    )
    assert january_stats.status_code == 200
    assert january_stats.json()["total_amount_cents"] == 1234

    december_stats = client.get(
        "/api/stats/monthly?month=2026-12", headers=app_headers()
    )
    assert december_stats.status_code == 200
    assert december_stats.json()["total_amount_cents"] == 4321

    months = client.get("/api/expenses/months", headers=app_headers())
    assert months.status_code == 200
    assert months.json()["items"] == ["2027-01", "2026-12"]


def test_unresolved_confirmed_fx_expense_does_not_pollute_stats_or_export_as_zero(
    client: TestClient,
) -> None:
    insert_confirmed_expense(
        amount_cents=1234,
        merchant="已结算外币账单",
        category="餐饮",
        expense_time=datetime(2026, 5, 4, 8, 0, tzinfo=UTC),
        confirmed_at=datetime(2026, 5, 4, 8, 1, tzinfo=UTC),
    )
    with SessionLocal() as db:
        db.add(
            Expense(
                tenant_id="owner",
                amount_cents=None,
                original_currency_code="USD",
                original_amount_minor=999,
                exchange_rate_to_cny=None,
                exchange_rate_source=None,
                fx_status="pending",
                merchant="待汇率外币账单",
                category="旅行",
                note="legacy migrated fx row",
                source="pytest",
                status="confirmed",
                expense_time=datetime(2026, 5, 5, 8, 0, tzinfo=UTC),
                created_at=datetime(2026, 5, 5, 8, 0, tzinfo=UTC),
                updated_at=datetime(2026, 5, 5, 8, 0, tzinfo=UTC),
                confirmed_at=datetime(2026, 5, 5, 8, 1, tzinfo=UTC),
            )
        )
        db.commit()

    stats = client.get("/api/stats/monthly?month=2026-05", headers=app_headers())
    assert stats.status_code == 200
    stats_payload = stats.json()
    assert stats_payload["total_amount_cents"] == 1234
    assert stats_payload["count"] == 1
    assert stats_payload["by_category"] == [
        {"category": "餐饮", "amount_cents": 1234, "count": 1},
    ]

    exported = client.get("/api/expenses/export.csv?month=2026-05", headers=app_headers())
    assert exported.status_code == 200
    rows = list(csv.DictReader(StringIO(exported.text.lstrip("\ufeff"))))
    unresolved = next(row for row in rows if row["merchant"] == "待汇率外币账单")
    assert unresolved["amount_cents"] == ""
    assert unresolved["amount_yuan"] == ""
    assert unresolved["original_currency_code"] == "USD"
    assert unresolved["original_amount_minor"] == "999"


def test_month_filter_can_follow_client_timezone_query(client: TestClient) -> None:
    insert_confirmed_expense(
        amount_cents=1851,
        merchant="手机时区边界账单",
        category="生活",
        expense_time=datetime(2026, 4, 30, 16, 30, tzinfo=UTC),
        confirmed_at=datetime(2026, 4, 30, 16, 31, tzinfo=UTC),
    )

    shanghai_page = client.get(
        "/api/expenses/confirmed?month=2026-05&timezone=Asia/Shanghai",
        headers=app_headers(),
    )
    assert shanghai_page.status_code == 200
    assert shanghai_page.json()["total"] == 1

    utc_april_page = client.get(
        "/api/expenses/confirmed?month=2026-04&timezone=UTC", headers=app_headers()
    )
    assert utc_april_page.status_code == 200
    assert utc_april_page.json()["total"] == 1

    utc_may_stats = client.get(
        "/api/stats/monthly?month=2026-05&timezone=UTC", headers=app_headers()
    )
    assert utc_may_stats.status_code == 200
    assert utc_may_stats.json()["total_amount_cents"] == 0

    shanghai_may_stats = client.get(
        "/api/stats/monthly?month=2026-05&timezone=Asia/Shanghai",
        headers=app_headers(),
    )
    assert shanghai_may_stats.status_code == 200
    assert shanghai_may_stats.json()["total_amount_cents"] == 1851

    shanghai_months = client.get(
        "/api/expenses/months?timezone=Asia/Shanghai", headers=app_headers()
    )
    assert shanghai_months.status_code == 200
    assert shanghai_months.json()["items"] == ["2026-05"]

    utc_months = client.get("/api/expenses/months?timezone=UTC", headers=app_headers())
    assert utc_months.status_code == 200
    assert utc_months.json()["items"] == ["2026-04"]

    shanghai_export = client.get(
        "/api/expenses/export.csv?month=2026-05&timezone=Asia/Shanghai",
        headers=app_headers(),
    )
    assert shanghai_export.status_code == 200
    assert "手机时区边界账单" in shanghai_export.text

    utc_may_export = client.get(
        "/api/expenses/export.csv?month=2026-05&timezone=UTC", headers=app_headers()
    )
    assert utc_may_export.status_code == 200
    assert "手机时区边界账单" not in utc_may_export.text

    invalid_timezone_page = client.get(
        "/api/expenses/confirmed?month=2026-04&timezone=Not/AZone",
        headers=app_headers(),
    )
    assert invalid_timezone_page.status_code == 200
    assert invalid_timezone_page.json()["total"] == 1


def test_confirmed_pagination_and_month_filters_are_server_side_contract(
    client: TestClient,
) -> None:
    for index, payload in enumerate(
        [
            {
                "amount_cents": 1100,
                "merchant": "早餐店",
                "category": "餐饮",
                "expense_time": "2026-05-01T00:00:00Z",
            },
            {
                "amount_cents": 2200,
                "merchant": "地铁",
                "category": "交通",
                "expense_time": "2026-05-02T00:00:00Z",
            },
            {
                "amount_cents": 3300,
                "merchant": "晚饭",
                "category": "餐饮",
                "expense_time": "2026-05-03T00:00:00Z",
            },
            {
                "amount_cents": 4400,
                "merchant": "上月",
                "category": "餐饮",
                "expense_time": "2026-04-30T00:00:00Z",
            },
        ],
        start=1,
    ):
        response = client.post(
            "/api/expenses/manual",
            headers=app_headers(),
            json={**payload, "note": f"分页测试 {index}"},
        )
        assert response.status_code == 200

    first_page = client.get(
        "/api/expenses/confirmed?month=2026-05&page=1&page_size=2",
        headers=app_headers(),
    )
    assert first_page.status_code == 200
    first_payload = first_page.json()
    assert first_payload["total"] == 3
    assert [item["merchant"] for item in first_payload["items"]] == ["晚饭", "地铁"]

    second_page = client.get(
        "/api/expenses/confirmed?month=2026-05&page=2&page_size=2",
        headers=app_headers(),
    )
    assert second_page.status_code == 200
    second_payload = second_page.json()
    assert second_payload["total"] == 3
    assert [item["merchant"] for item in second_payload["items"]] == ["早餐店"]

    category_page = client.get(
        "/api/expenses/confirmed?month=2026-05&category=餐饮&page=1&page_size=50",
        headers=app_headers(),
    )
    assert category_page.status_code == 200
    category_payload = category_page.json()
    assert category_payload["total"] == 2
    assert [item["merchant"] for item in category_payload["items"]] == [
        "晚饭",
        "早餐店",
    ]

    stats = client.get("/api/stats/monthly?month=2026-05", headers=app_headers())
    assert stats.status_code == 200
    stats_payload = stats.json()
    assert stats_payload["total_amount_cents"] == 6600
    assert stats_payload["count"] == 3

    months = client.get("/api/expenses/months", headers=app_headers())
    assert months.status_code == 200
    assert months.json()["items"] == ["2026-05", "2026-04"]
