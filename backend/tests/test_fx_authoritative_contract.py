from __future__ import annotations

import csv
from decimal import Decimal
from io import StringIO

from api_contract_helpers import confirm_expense_api
from fastapi.testclient import TestClient


def _set_manual_rate(
    client: TestClient,
    *, identity,
    currency_code: str,
    rate_date: str,
    rate_to_cny: str,
) -> None:
    response = client.put(
        f"/api/exchange-rates/{currency_code}/{rate_date}",
        headers=identity.app_headers,
        json={
            "currency_code": currency_code,
            "rate_date": rate_date,
            "rate_to_cny": rate_to_cny,
            "source": "manual",
        },
    )
    assert response.status_code == 200, response.json()


def _create_foreign_manual_expense(
    client: TestClient,
    *, identity,
    original_amount_minor: int,
    merchant: str,
    category: str = "餐饮",
    spent_at: str = "2026-05-04T02:00:00Z",
) -> dict:
    response = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "original_currency_code": "USD",
            "original_amount_minor": original_amount_minor,
            "spent_at": spent_at,
            "merchant": merchant,
            "category": category,
        },
    )
    assert response.status_code == 200, response.json()
    return response.json()


def _csv_rows(response_text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(StringIO(response_text.lstrip("\ufeff"))))


def test_foreign_home_amount_drives_stats_reports_budget_and_export(
    client: TestClient, *, identity,
) -> None:
    _set_manual_rate(client, currency_code="USD", rate_date="2026-05-04", rate_to_cny="7", identity=identity)

    expense = _create_foreign_manual_expense(
        client,
        original_amount_minor=12345,
        merchant="Home Amount Cafe",
     identity=identity)
    assert expense["status"] == "confirmed"
    assert expense["amount_cents"] == 86415
    assert expense["home_amount_cents"] == 86415
    assert expense["original_amount_minor"] == 12345
    assert expense["original_currency_code"] == "USD"
    assert Decimal(expense["exchange_rate_to_cny"]) == Decimal("7.00000000")

    stats = client.get(
        "/api/stats/monthly?month=2026-05&timezone=UTC",
        headers=identity.app_headers,
    )
    assert stats.status_code == 200, stats.json()
    assert stats.json()["total_amount_cents"] == 86415
    assert stats.json()["by_category"] == [
        {"category": "餐饮", "amount_cents": 86415, "count": 1}
    ]

    report = client.get(
        "/api/reports/overview?month=2026-05&timezone=UTC&granularity=day&top_n=3",
        headers=identity.app_headers,
    )
    assert report.status_code == 200, report.json()
    report_body = report.json()
    assert report_body["total_amount_cents"] == 86415
    assert sum(point["amount_cents"] for point in report_body["trend"]) == 86415
    assert report_body["merchant_ranking"] == [
        {"merchant": "Home Amount Cafe", "amount_cents": 86415, "count": 1}
    ]
    assert report_body["category_comparison"] == [
        {
            "category": "餐饮",
            "amount_cents": 86415,
            "count": 1,
            "previous_amount_cents": 0,
            "previous_count": 0,
            "delta_amount_cents": 86415,
            "delta_count": 1,
            "year_over_year_amount_cents": 0,
            "year_over_year_count": 0,
            "year_over_year_delta_amount_cents": 86415,
            "year_over_year_delta_count": 1,
        }
    ]

    budget = client.put(
        "/api/budgets/monthly/2026-05?timezone=UTC",
        headers=identity.app_headers,
        json={
            "total_amount_cents": 100000,
            "category_budgets": [{"category": "餐饮", "amount_cents": 90000}],
        },
    )
    assert budget.status_code == 200, budget.json()
    budget_body = budget.json()
    assert budget_body["spent_amount_cents"] == 86415
    assert budget_body["remaining_amount_cents"] == 13585
    assert budget_body["category_budgets"] == [
        {
            "category": "餐饮",
            "amount_cents": 90000,
            "spent_amount_cents": 86415,
            "remaining_amount_cents": 3585,
            "overspent_amount_cents": 0,
        }
    ]

    exported = client.get("/api/expenses/export.csv?month=2026-05", headers=identity.app_headers)
    assert exported.status_code == 200, exported.text
    rows = _csv_rows(exported.text)
    assert len(rows) == 1
    assert rows[0]["amount_cents"] == "86415"
    assert rows[0]["original_currency_code"] == "USD"
    assert rows[0]["original_amount_minor"] == "12345"
    assert rows[0]["exchange_rate_to_cny"] == "7.00000000"
    assert rows[0]["exchange_rate_source"] == "manual"


def test_missing_foreign_rate_stays_pending_without_fake_home_amount(
    client: TestClient, *, identity,
) -> None:
    response = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "original_currency_code": "USD",
            "original_amount_minor": 12345,
            "spent_at": "2026-05-04T02:00:00Z",
            "merchant": "Missing Rate Cafe",
            "category": "餐饮",
        },
    )
    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["status"] == "pending"
    assert payload["fx_status"] == "pending"
    assert payload["amount_cents"] is None
    assert payload["home_amount_cents"] is None
    assert payload["exchange_rate_to_cny"] is None
    assert payload["fx_rate"] is None
    assert payload["original_amount_minor"] == 12345

    stats = client.get("/api/stats/monthly?month=2026-05", headers=identity.app_headers)
    assert stats.status_code == 200, stats.json()
    assert stats.json()["total_amount_cents"] == 0
    assert stats.json()["count"] == 0

    confirm = confirm_expense_api(client, payload["id"], headers=identity.app_headers)
    assert confirm.status_code == 409
    assert confirm.json()["error"] == "exchange_rate_pending"

    detail = client.get(f"/api/expenses/{payload['id']}", headers=identity.app_headers)
    assert detail.status_code == 200, detail.json()
    assert detail.json()["status"] == "pending"
    assert detail.json()["amount_cents"] is None


def test_resolved_foreign_snapshot_does_not_drift_after_rate_update(
    client: TestClient, *, identity,
) -> None:
    _set_manual_rate(client, currency_code="USD", rate_date="2026-05-04", rate_to_cny="7", identity=identity)
    first = _create_foreign_manual_expense(
        client,
        original_amount_minor=10000,
        merchant="Frozen Rate Cafe",
        category="餐饮",
     identity=identity)
    assert first["amount_cents"] == 70000
    assert Decimal(first["exchange_rate_to_cny"]) == Decimal("7.00000000")

    _set_manual_rate(client, currency_code="USD", rate_date="2026-05-04", rate_to_cny="8", identity=identity)

    frozen = client.get(f"/api/expenses/{first['id']}", headers=identity.app_headers)
    assert frozen.status_code == 200, frozen.json()
    assert frozen.json()["amount_cents"] == 70000
    assert Decimal(frozen.json()["exchange_rate_to_cny"]) == Decimal("7.00000000")
    assert frozen.json()["exchange_rate_source"] == "manual"

    second = _create_foreign_manual_expense(
        client,
        original_amount_minor=10000,
        merchant="Updated Rate Cafe",
        category="交通",
     identity=identity)
    assert second["amount_cents"] == 80000
    assert Decimal(second["exchange_rate_to_cny"]) == Decimal("8.00000000")

    stats = client.get("/api/stats/monthly?month=2026-05", headers=identity.app_headers)
    assert stats.status_code == 200, stats.json()
    assert stats.json()["total_amount_cents"] == 150000
    assert sorted(stats.json()["by_category"], key=lambda row: row["category"]) == [
        {"category": "交通", "amount_cents": 80000, "count": 1},
        {"category": "餐饮", "amount_cents": 70000, "count": 1},
    ]


def test_csv_import_accepts_old_home_rows_and_resolves_new_foreign_rows_with_backend_rate(
    client: TestClient, *, identity,
) -> None:
    old_csv = (
        "amount_yuan,merchant,category,expense_time\n"
        "12.34,Legacy CSV Cafe,餐饮,2026-05-04T00:00:00Z\n"
    )
    old_created = client.post(
        "/api/imports/csv",
        headers=identity.app_headers,
        files={"csv_file": ("old.csv", old_csv.encode("utf-8"), "text/csv")},
    )
    assert old_created.status_code == 201, old_created.json()
    old_apply = client.post(
        f"/api/imports/csv/{old_created.json()['public_id']}/apply",
        headers=identity.app_headers,
        json={"batch_size": 10},
    )
    assert old_apply.status_code == 200, old_apply.json()

    pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    assert pending.status_code == 200, pending.json()
    old_expense = next(item for item in pending.json() if item["merchant"] == "Legacy CSV Cafe")
    assert old_expense["amount_cents"] == 1234
    assert old_expense["original_currency_code"] == "CNY"
    assert old_expense["original_amount_minor"] == 1234
    assert Decimal(old_expense["exchange_rate_to_cny"]) == Decimal("1.00000000")
    assert old_expense["exchange_rate_source"] == "base"
    assert old_expense["fx_status"] == "ready"

    _set_manual_rate(client, currency_code="USD", rate_date="2026-05-04", rate_to_cny="7", identity=identity)
    new_csv = (
        "amount_cents,original_currency_code,original_amount_minor,"
        "exchange_rate_to_cny,exchange_rate_date,merchant,category,expense_time\n"
        ",USD,12345,99.9999,2026-05-04,Imported USD Cafe,餐饮,2026-05-04T02:00:00Z\n"
    )
    new_created = client.post(
        "/api/imports/csv",
        headers=identity.app_headers,
        files={"csv_file": ("new.csv", new_csv.encode("utf-8"), "text/csv")},
    )
    assert new_created.status_code == 201, new_created.json()
    public_id = new_created.json()["public_id"]

    rows = client.get(f"/api/imports/csv/{public_id}/rows", headers=identity.app_headers)
    assert rows.status_code == 200, rows.json()
    assert rows.json()["items"][0]["original_currency_code"] == "USD"
    assert rows.json()["items"][0]["original_amount_minor"] == 12345
    assert rows.json()["items"][0]["exchange_rate_to_cny"] is None

    new_apply = client.post(
        f"/api/imports/csv/{public_id}/apply",
        headers=identity.app_headers,
        json={"batch_size": 10},
    )
    assert new_apply.status_code == 200, new_apply.json()

    pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    assert pending.status_code == 200, pending.json()
    new_expense = next(item for item in pending.json() if item["merchant"] == "Imported USD Cafe")
    assert new_expense["amount_cents"] == 86415
    assert new_expense["home_amount_cents"] == 86415
    assert new_expense["original_currency_code"] == "USD"
    assert new_expense["original_amount_minor"] == 12345
    assert Decimal(new_expense["exchange_rate_to_cny"]) == Decimal("7.00000000")
    assert new_expense["exchange_rate_source"] == "manual"
    assert new_expense["fx_status"] == "ready"
