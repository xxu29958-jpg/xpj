"""Consumer contract for the confirmed expense and offset event stream."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from io import StringIO

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.schemas import ConfirmedExpenseStreamItem
from app.services.budget_baseline_service._spent_reader import (
    total_confirmed_spent_cents,
)
from app.services.category_service import list_category_summary
from app.services.goal_spending_response import month_spend_totals
from app.services.insight_radar_service import cashflow_radar
from app.services.monthly_report_service import compose_monthly_report
from app.services.reports_service import reports_overview
from app.services.web_stats_service import confirmed_by_day
from tests.expense_correction_support import idem


def test_confirmed_stream_wire_is_one_stable_envelope() -> None:
    """Every stream row carries its root; only offset rows carry an offset."""
    fields = ConfirmedExpenseStreamItem.model_fields
    assert {
        "entry_kind",
        "stream_date",
        "stream_sort_time",
        "stream_sort_id",
        "stream_amount_cents",
        "root",
        "offset",
        "lineage_status",
        "lineage_home_net_cents",
    } <= fields.keys()
    assert fields["root"].is_required()
    assert not fields["offset"].is_required()


def _manual(
    client: TestClient,
    identity,
    *,
    merchant: str,
    amount_cents: int,
    expense_time: str,
    category: str = "旅游",
    tags: str = "旅行",
) -> dict:
    response = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": amount_cents,
            "merchant": merchant,
            "category": category,
            "tags": tags,
            "expense_time": expense_time,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _offset(
    client: TestClient,
    identity,
    expense: dict,
    *,
    kind: str,
    accounting_date: str,
    amount_cents: int | None = None,
) -> dict:
    payload = {
        "kind": kind,
        "accounting_date": accounting_date,
        "reason": f"登记{kind}",
        "expected_row_version": expense["row_version"],
    }
    if amount_cents is not None:
        payload["original_amount_minor"] = amount_cents
    response = client.post(
        f"/api/expenses/{expense['id']}/offsets",
        headers=idem(identity.app_headers),
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _stream(client: TestClient, identity, **params: str | int) -> dict:
    response = client.get(
        "/api/expenses/confirmed",
        headers=identity.app_headers,
        params={"timezone": "Asia/Shanghai", **params},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_offset_stream_filtering_uses_its_date_category_and_root_tags(
    client: TestClient,
    *,
    identity,
) -> None:
    expense = _manual(
        client,
        identity,
        merchant="夏日酒店",
        amount_cents=1200,
        expense_time="2026-08-15T04:00:00Z",
    )
    created = _offset(
        client,
        identity,
        expense,
        kind="refund",
        accounting_date="2026-09-03",
        amount_cents=300,
    )
    offset = created["active_offsets"][0]
    assert offset["stream_sort_time"] == offset["created_at"]
    assert isinstance(offset["stream_sort_id"], int)
    correction = client.post(
        f"/api/expenses/{expense['id']}/offsets/{offset['public_id']}/corrections",
        headers=idem(identity.app_headers),
        json={
            "original_amount_minor": 300,
            "accounting_date": "2026-09-03",
            "category": "购物",
            "offset_reason": "退款归到购物",
            "correction_reason": "更正退款归属",
            "expected_row_version": offset["row_version"],
        },
    )
    assert correction.status_code == 201, correction.text

    september = _stream(client, identity, month="2026-09", category="购物", tag="旅行")
    assert september["total"] == 1
    entry = september["items"][0]
    assert entry["entry_kind"] == "offset"
    assert entry["offset"]["kind"] == "refund"
    assert entry["stream_date"] == "2026-09-03"
    assert entry["stream_sort_time"] == offset["stream_sort_time"]
    assert entry["stream_sort_id"] == offset["stream_sort_id"]
    assert entry["stream_amount_cents"] == -300
    assert entry["root"]["id"] == expense["id"]
    assert entry["root"]["public_id"] == expense["public_id"]
    assert entry["root"]["merchant"] == "夏日酒店"
    assert entry["offset"]["home_currency_code"] == entry["root"]["home_currency"]
    assert entry["offset"]["original_currency_code"] == entry["root"]["original_currency_code"]
    assert _stream(client, identity, month="2026-09", category="旅游", tag="旅行")["total"] == 0

    august = _stream(client, identity, month="2026-08", category="旅游", tag="旅行")
    root = august["items"][0]
    assert root["entry_kind"] == "expense"
    assert root["offset"] is None
    assert root["root"]["id"] == expense["id"]
    assert root["stream_date"] == "2026-08-15"
    assert root["stream_amount_cents"] == 1200
    assert root["lineage_status"] == "partially_refunded"
    assert root["lineage_home_net_cents"] == 900


def test_stream_pagination_counts_entries_orders_offsets_and_drops_voided(
    client: TestClient,
    *,
    identity,
) -> None:
    expense = _manual(
        client,
        identity,
        merchant="多次退款订单",
        amount_cents=1000,
        expense_time="2026-08-10T04:00:00Z",
    )
    first = _offset(
        client,
        identity,
        expense,
        kind="refund",
        accounting_date="2026-09-02",
        amount_cents=200,
    )
    second = _offset(
        client,
        identity,
        first["root"],
        kind="chargeback",
        accounting_date="2026-09-03",
        amount_cents=100,
    )

    page_one = _stream(client, identity, month="2026-09", page=1, page_size=1)
    page_two = _stream(client, identity, month="2026-09", page=2, page_size=1)
    assert page_one["total"] == page_two["total"] == 2
    assert page_one["items"][0]["offset"]["kind"] == "chargeback"
    assert page_two["items"][0]["offset"]["kind"] == "refund"

    chargeback = next(item for item in second["active_offsets"] if item["kind"] == "chargeback")
    voided = client.post(
        f"/api/expenses/{expense['id']}/offsets/{chargeback['public_id']}/voids",
        headers=idem(identity.app_headers),
        json={"void_reason": "拒付登记有误", "expected_row_version": chargeback["row_version"]},
    )
    assert voided.status_code == 201, voided.text
    remaining = _stream(client, identity, month="2026-09")
    assert remaining["total"] == 1
    assert remaining["items"][0]["offset"]["kind"] == "refund"


def test_reversal_stream_is_a_zero_contribution_event_and_zeroes_its_root(
    client: TestClient,
    *,
    identity,
) -> None:
    expense = _manual(
        client,
        identity,
        merchant="重复记账",
        amount_cents=800,
        expense_time="2026-08-20T04:00:00Z",
        tags="复核",
    )
    _offset(
        client,
        identity,
        expense,
        kind="reversal",
        accounting_date="2026-09-04",
    )

    august = _stream(client, identity, month="2026-08", tag="复核")
    root = august["items"][0]
    assert root["entry_kind"] == "expense"
    assert root["lineage_status"] == "reversed"
    assert root["lineage_home_net_cents"] == 0
    assert root["stream_amount_cents"] == 0

    september = _stream(client, identity, month="2026-09", tag="复核")
    reversal = september["items"][0]
    assert reversal["entry_kind"] == "offset"
    assert reversal["offset"]["kind"] == "reversal"
    assert reversal["stream_date"] == "2026-09-04"
    assert reversal["offset"]["amount_cents"] == 800
    assert reversal["root"]["id"] == expense["id"]
    assert reversal["stream_amount_cents"] == 0


def _assert_refund_month_stats(client: TestClient, identity) -> None:
    august = client.get(
        "/api/stats/monthly",
        headers=identity.app_headers,
        params={"month": "2026-08", "timezone": "Asia/Shanghai", "tag": "旅行"},
    )
    september = client.get(
        "/api/stats/monthly",
        headers=identity.app_headers,
        params={"month": "2026-09", "timezone": "Asia/Shanghai", "tag": "旅行"},
    )
    assert august.status_code == september.status_code == 200
    assert august.json()["total_amount_cents"] == 1200
    assert august.json()["count"] == 1
    assert september.json()["total_amount_cents"] == -300
    assert september.json()["count"] == 1
    assert september.json()["by_category"] == [
        {"category": "旅游", "amount_cents": -300, "count": 1},
    ]


def _assert_refund_service_consumers() -> None:
    with SessionLocal() as db:
        assert confirmed_by_day(db, "owner", "2026-09", tag="旅行") == [
            {
                "date": "2026-09-03",
                "amount_cents": -300,
                "amount_yuan": -3.0,
                "count": 1,
            }
        ]
        assert total_confirmed_spent_cents(
            db,
            tenant_id="owner",
            month="2026-09",
            timezone_name="Asia/Shanghai",
        ) == -300
        goal_totals = month_spend_totals(
            db,
            tenant_id="owner",
            month="2026-09",
            timezone_name="Asia/Shanghai",
        )
        assert goal_totals.total_amount_cents == -300
        assert goal_totals.by_category == {"旅游": -300}
        report = compose_monthly_report(
            db,
            tenant_id="owner",
            year_month="2026-09",
            timezone_name="Asia/Shanghai",
        )
        assert report.total_cents == -300
        assert report.expense_count == 1
        overview = reports_overview(
            db,
            month="2026-09",
            tenant_id="owner",
            timezone_name="Asia/Shanghai",
        )
        assert overview["total_amount_cents"] == -300
        assert overview["count"] == 1
        assert next(
            point for point in overview["trend"] if point["bucket"] == "2026-09-03"
        )["amount_cents"] == -300
        assert overview["merchant_ranking"][0]["merchant"] == "跨月退款订单"
        assert overview["merchant_ranking"][0]["amount_cents"] == -300
        september_category = next(
            item
            for item in overview["category_comparison"]
            if item["category"] == "旅游"
        )
        assert september_category["amount_cents"] == -300
        category_dashboard = list_category_summary(
            db,
            tenant_id="owner",
            month="2026-09",
            timezone_name="Asia/Shanghai",
        )
        travel = next(
            item for item in category_dashboard.summaries if item.category == "旅游"
        )
        assert travel.confirmed_amount_cents == -300
        assert travel.confirmed_count == 1
        september_cashflow = next(
            item
            for item in cashflow_radar(
                db,
                tenant_id="owner",
                look_back_months=2,
                now=datetime(2026, 9, 15, tzinfo=UTC),
                timezone_name="Asia/Shanghai",
            )
            if item.year_month == "2026-09"
        )
        assert september_cashflow.expense_cents == -300


def _assert_refund_export_and_lifestyle(client: TestClient, identity) -> None:
    months = client.get(
        "/api/expenses/months",
        headers=identity.app_headers,
        params={"timezone": "Asia/Shanghai"},
    )
    assert months.status_code == 200
    assert months.json()["items"][:2] == ["2026-09", "2026-08"]

    exported = client.get(
        "/api/expenses/export.csv",
        headers=identity.app_headers,
        params={"month": "2026-09", "timezone": "Asia/Shanghai", "tag": "旅行"},
    )
    assert exported.status_code == 200
    rows = list(csv.DictReader(StringIO(exported.text.lstrip("\ufeff"))))
    assert len(rows) == 1
    assert rows[0]["entry_kind"] == "offset"
    assert rows[0]["offset_kind"] == "refund"
    assert rows[0]["stream_date"] == "2026-09-03"
    assert rows[0]["stream_amount_cents"] == "-300"
    assert rows[0]["merchant"] == "跨月退款订单"

    lifestyle = client.get(
        "/api/stats/lifestyle",
        headers=identity.app_headers,
        params={"month": "2026-09", "timezone": "Asia/Shanghai"},
    )
    assert lifestyle.status_code == 200
    merchant = next(
        item
        for item in lifestyle.json()["frequent_merchants"]
        if item["merchant"] == "跨月退款订单"
    )
    assert merchant["amount_cents"] == -300


def test_refund_stream_projection_drives_month_stats_calendar_and_month_picker(
    client: TestClient,
    *,
    identity,
) -> None:
    expense = _manual(
        client,
        identity,
        merchant="跨月退款订单",
        amount_cents=1200,
        expense_time="2026-08-15T04:00:00Z",
        tags="旅行",
    )
    _offset(
        client,
        identity,
        expense,
        kind="refund",
        accounting_date="2026-09-03",
        amount_cents=300,
    )
    _assert_refund_month_stats(client, identity)
    _assert_refund_service_consumers()
    _assert_refund_export_and_lifestyle(client, identity)


def test_reversal_zero_contribution_drives_original_and_event_month_stats(
    client: TestClient,
    *,
    identity,
) -> None:
    expense = _manual(
        client,
        identity,
        merchant="整笔冲销订单",
        amount_cents=800,
        expense_time="2026-08-20T04:00:00Z",
        tags="复核",
    )
    _offset(
        client,
        identity,
        expense,
        kind="reversal",
        accounting_date="2026-09-04",
    )

    august = client.get(
        "/api/stats/monthly",
        headers=identity.app_headers,
        params={"month": "2026-08", "timezone": "Asia/Shanghai", "tag": "复核"},
    )
    september = client.get(
        "/api/stats/monthly",
        headers=identity.app_headers,
        params={"month": "2026-09", "timezone": "Asia/Shanghai", "tag": "复核"},
    )
    assert august.status_code == september.status_code == 200
    assert august.json()["total_amount_cents"] == 0
    assert august.json()["count"] == 1
    assert september.json()["total_amount_cents"] == 0
    assert september.json()["count"] == 1

    with SessionLocal() as db:
        assert confirmed_by_day(db, "owner", "2026-08", tag="复核")[0]["amount_cents"] == 0
        assert confirmed_by_day(db, "owner", "2026-09", tag="复核")[0]["amount_cents"] == 0

    august_export = client.get(
        "/api/expenses/export.csv",
        headers=identity.app_headers,
        params={"month": "2026-08", "timezone": "Asia/Shanghai", "tag": "复核"},
    )
    september_export = client.get(
        "/api/expenses/export.csv",
        headers=identity.app_headers,
        params={"month": "2026-09", "timezone": "Asia/Shanghai", "tag": "复核"},
    )
    august_row = next(csv.DictReader(StringIO(august_export.text.lstrip("\ufeff"))))
    september_row = next(
        csv.DictReader(StringIO(september_export.text.lstrip("\ufeff")))
    )
    assert august_row["entry_kind"] == "expense"
    assert august_row["stream_amount_cents"] == "0"
    assert september_row["entry_kind"] == "offset"
    assert september_row["offset_kind"] == "reversal"
    assert september_row["stream_amount_cents"] == "0"
