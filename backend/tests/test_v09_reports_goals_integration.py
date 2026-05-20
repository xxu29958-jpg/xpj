from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Expense, LedgerMember
from app.services.time_service import now_utc

VIEWER_WRITE_MESSAGE = "当前角色为只读，无法修改账本。"


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
    status_time = confirmed_at or now
    rejected_at = status_time if status == "rejected" else None
    with SessionLocal() as db:
        db.add(
            Expense(
                tenant_id=tenant_id,
                amount_cents=amount_cents,
                merchant=merchant,
                category=category,
                note="",
                source="pytest-v09-integration",
                status=status,
                expense_time=expense_time,
                created_at=status_time,
                updated_at=status_time,
                confirmed_at=confirmed_at,
                rejected_at=rejected_at,
            )
        )
        db.commit()


def _create_goal(
    client: TestClient,
    *,
    headers: dict[str, str],
    name: str,
    month: str,
    target_amount_cents: int,
    category: str | None = None,
    timezone: str = "Asia/Shanghai",
) -> dict:
    body: dict[str, object] = {
        "name": name,
        "month": month,
        "target_amount_cents": target_amount_cents,
    }
    if category is not None:
        body["category"] = category
    response = client.post(f"/api/goals?timezone={timezone}", headers=headers, json=body)
    assert response.status_code == 201, response.json()
    return response.json()


def _demote_owner_ledger_to_viewer() -> None:
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1))
        assert member is not None
        member.role = "viewer"
        db.commit()


def _assert_permission_denied(response, *, label: str) -> None:
    assert response.status_code == 403, label
    payload = response.json()
    assert payload["error"] == "permission_denied", label
    assert payload["message"] == VIEWER_WRITE_MESSAGE, label


def test_reports_goals_and_monthly_stats_share_confirmed_time_scope(
    client: TestClient, *, identity,
) -> None:
    _insert_expense(
        amount_cents=1200,
        merchant="早餐店",
        category="餐饮",
        status="confirmed",
        expense_time=datetime(2026, 5, 1, 1, 0, tzinfo=UTC),
        confirmed_at=datetime(2026, 6, 1, 0, 0, tzinfo=UTC),
    )
    _insert_expense(
        amount_cents=2300,
        merchant="地铁",
        category="交通",
        status="confirmed",
        expense_time=None,
        confirmed_at=datetime(2026, 4, 30, 16, 30, tzinfo=UTC),
    )
    _insert_expense(
        amount_cents=500,
        merchant="上月早餐店",
        category="餐饮",
        status="confirmed",
        expense_time=datetime(2026, 4, 10, 1, 0, tzinfo=UTC),
        confirmed_at=datetime(2026, 4, 10, 1, 1, tzinfo=UTC),
    )
    _insert_expense(
        amount_cents=9999,
        merchant="待确认不应统计",
        category="餐饮",
        status="pending",
        expense_time=datetime(2026, 5, 1, 2, 0, tzinfo=UTC),
        confirmed_at=None,
    )
    _insert_expense(
        amount_cents=8888,
        merchant="已拒绝不应统计",
        category="交通",
        status="rejected",
        expense_time=datetime(2026, 5, 1, 3, 0, tzinfo=UTC),
        confirmed_at=None,
    )
    _insert_expense(
        tenant_id="tester_1",
        amount_cents=7777,
        merchant="灰度账本不应串入",
        category="餐饮",
        status="confirmed",
        expense_time=datetime(2026, 5, 1, 1, 0, tzinfo=UTC),
        confirmed_at=datetime(2026, 5, 1, 1, 1, tzinfo=UTC),
    )

    _create_goal(
        client,
        headers=identity.app_headers,
        name="本月总支出",
        month="2026-05",
        target_amount_cents=5000,
    )
    _create_goal(
        client,
        headers=identity.app_headers,
        name="餐饮目标",
        month="2026-05",
        category="餐饮",
        target_amount_cents=2000,
    )

    stats = client.get(
        "/api/stats/monthly?month=2026-05&timezone=Asia/Shanghai",
        headers=identity.app_headers,
    )
    assert stats.status_code == 200, stats.json()
    stats_payload = stats.json()
    assert stats_payload["total_amount_cents"] == 3500
    assert stats_payload["count"] == 2
    assert stats_payload["by_category"] == [
        {"category": "交通", "amount_cents": 2300, "count": 1},
        {"category": "餐饮", "amount_cents": 1200, "count": 1},
    ]

    report = client.get(
        "/api/reports/overview?month=2026-05&timezone=Asia/Shanghai&granularity=day",
        headers=identity.app_headers,
    )
    assert report.status_code == 200, report.json()
    report_payload = report.json()
    assert report_payload["total_amount_cents"] == stats_payload["total_amount_cents"]
    assert report_payload["count"] == stats_payload["count"]
    assert report_payload["previous_total_amount_cents"] == 500
    assert report_payload["trend"][0] == {
        "bucket": "2026-05-01",
        "label": "05-01",
        "amount_cents": 3500,
        "count": 2,
    }
    assert report_payload["merchant_ranking"] == [
        {"merchant": "地铁", "amount_cents": 2300, "count": 1},
        {"merchant": "早餐店", "amount_cents": 1200, "count": 1},
    ]
    assert "待确认不应统计" not in str(report_payload)
    assert "已拒绝不应统计" not in str(report_payload)
    assert "灰度账本不应串入" not in str(report_payload)

    goals = client.get(
        "/api/goals?month=2026-05&timezone=Asia/Shanghai",
        headers=identity.app_headers,
    )
    assert goals.status_code == 200, goals.json()
    goal_payloads = {item["name"]: item for item in goals.json()["items"]}
    assert goal_payloads["本月总支出"]["spent_amount_cents"] == 3500
    assert goal_payloads["本月总支出"]["progress_percent"] == 70
    assert goal_payloads["餐饮目标"]["spent_amount_cents"] == 1200
    assert goal_payloads["餐饮目标"]["progress_percent"] == 60

    utc_stats = client.get(
        "/api/stats/monthly?month=2026-05&timezone=UTC",
        headers=identity.app_headers,
    )
    assert utc_stats.status_code == 200, utc_stats.json()
    assert utc_stats.json()["total_amount_cents"] == 1200

    utc_report = client.get(
        "/api/reports/overview?month=2026-05&timezone=UTC",
        headers=identity.app_headers,
    )
    assert utc_report.status_code == 200, utc_report.json()
    assert utc_report.json()["total_amount_cents"] == 1200

    utc_goals = client.get(
        "/api/goals?month=2026-05&timezone=UTC",
        headers=identity.app_headers,
    )
    assert utc_goals.status_code == 200, utc_goals.json()
    utc_goal_payloads = {item["name"]: item for item in utc_goals.json()["items"]}
    assert utc_goal_payloads["本月总支出"]["spent_amount_cents"] == 1200
    assert utc_goal_payloads["餐饮目标"]["spent_amount_cents"] == 1200


def test_reports_goals_stats_isolate_ledgers_and_viewer_goal_writes_are_denied(
    client: TestClient, *, identity,
) -> None:
    _insert_expense(
        amount_cents=1100,
        merchant="Owner 早餐",
        category="餐饮",
        status="confirmed",
        expense_time=datetime(2026, 5, 2, 0, 0, tzinfo=UTC),
        confirmed_at=datetime(2026, 5, 2, 0, 1, tzinfo=UTC),
    )
    _insert_expense(
        tenant_id="tester_1",
        amount_cents=6600,
        merchant="Gray 地铁",
        category="交通",
        status="confirmed",
        expense_time=datetime(2026, 5, 2, 0, 0, tzinfo=UTC),
        confirmed_at=datetime(2026, 5, 2, 0, 1, tzinfo=UTC),
    )
    owner_goal = _create_goal(
        client,
        headers=identity.app_headers,
        name="Owner Goal",
        month="2026-05",
        target_amount_cents=5000,
        timezone="UTC",
    )
    _create_goal(
        client,
        headers=identity.gray_app_headers,
        name="Gray Goal",
        month="2026-05",
        target_amount_cents=7000,
        timezone="UTC",
    )

    owner_stats = client.get(
        "/api/stats/monthly?month=2026-05&timezone=UTC",
        headers=identity.app_headers,
    )
    gray_stats = client.get(
        "/api/stats/monthly?month=2026-05&timezone=UTC",
        headers=identity.gray_app_headers,
    )
    assert owner_stats.status_code == 200, owner_stats.json()
    assert gray_stats.status_code == 200, gray_stats.json()
    assert owner_stats.json()["total_amount_cents"] == 1100
    assert gray_stats.json()["total_amount_cents"] == 6600

    owner_report = client.get(
        "/api/reports/overview?month=2026-05&timezone=UTC",
        headers=identity.app_headers,
    )
    gray_report = client.get(
        "/api/reports/overview?month=2026-05&timezone=UTC",
        headers=identity.gray_app_headers,
    )
    assert owner_report.status_code == 200, owner_report.json()
    assert gray_report.status_code == 200, gray_report.json()
    assert owner_report.json()["total_amount_cents"] == 1100
    assert gray_report.json()["total_amount_cents"] == 6600
    assert "Gray 地铁" not in str(owner_report.json())
    assert "Owner 早餐" not in str(gray_report.json())

    owner_goals = client.get(
        "/api/goals?month=2026-05&timezone=UTC",
        headers=identity.app_headers,
    )
    gray_goals = client.get(
        "/api/goals?month=2026-05&timezone=UTC",
        headers=identity.gray_app_headers,
    )
    assert owner_goals.status_code == 200, owner_goals.json()
    assert gray_goals.status_code == 200, gray_goals.json()
    assert [(item["name"], item["spent_amount_cents"]) for item in owner_goals.json()["items"]] == [
        ("Owner Goal", 1100)
    ]
    assert [(item["name"], item["spent_amount_cents"]) for item in gray_goals.json()["items"]] == [
        ("Gray Goal", 6600)
    ]

    _demote_owner_ledger_to_viewer()
    viewer_report = client.get(
        "/api/reports/overview?month=2026-05&timezone=UTC",
        headers=identity.app_headers,
    )
    viewer_goals = client.get(
        "/api/goals?month=2026-05&timezone=UTC",
        headers=identity.app_headers,
    )
    assert viewer_report.status_code == 200, viewer_report.json()
    assert viewer_report.json()["total_amount_cents"] == 1100
    assert viewer_goals.status_code == 200, viewer_goals.json()
    assert viewer_goals.json()["items"][0]["name"] == "Owner Goal"

    _assert_permission_denied(
        client.post(
            "/api/goals?timezone=UTC",
            headers=identity.app_headers,
            json={
                "name": "Viewer Write",
                "month": "2026-05",
                "target_amount_cents": 3000,
            },
        ),
        label="viewer goal create",
    )
    _assert_permission_denied(
        client.patch(
            f"/api/goals/{owner_goal['public_id']}?timezone=UTC",
            headers=identity.app_headers,
            json={"target_amount_cents": 3000},
        ),
        label="viewer goal patch",
    )
