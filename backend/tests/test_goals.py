"""v0.9 Goals API: monthly spending-limit goals with progress."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Expense, LedgerMember
from app.services.time_service import now_utc

VIEWER_WRITE_MESSAGE = "当前角色为只读，无法修改账本。"


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


def _assert_permission_denied(response, *, label: str) -> None:
    assert response.status_code == 403, label
    payload = response.json()
    assert payload["error"] == "permission_denied", label
    assert payload["message"] == VIEWER_WRITE_MESSAGE, label


def test_goals_create_list_and_progress_by_total_and_category(client: TestClient, *, identity) -> None:
    _manual_expense(
        client,
        headers=identity.app_headers,
        amount_cents=1200,
        merchant="早餐店",
        category="餐饮",
        expense_time="2026-05-01T00:00:00Z",
    )
    _manual_expense(
        client,
        headers=identity.app_headers,
        amount_cents=3000,
        merchant="地铁",
        category="交通",
        expense_time="2026-05-02T00:00:00Z",
    )
    _insert_expense(
        amount_cents=9999,
        merchant="待确认不应统计",
        category="餐饮",
        status="pending",
        expense_time=datetime(2026, 5, 3, 0, 0, tzinfo=UTC),
        confirmed_at=None,
    )

    total_goal = client.post(
        "/api/goals?timezone=UTC",
        headers=identity.app_headers,
        json={
            "name": "本月总支出",
            "month": "2026-05",
            "target_amount_cents": 5000,
        },
    )
    assert total_goal.status_code == 201, total_goal.json()
    total_payload = total_goal.json()
    assert total_payload["spent_amount_cents"] == 4200
    assert total_payload["remaining_amount_cents"] == 800
    assert total_payload["progress_percent"] == 84
    assert total_payload["progress_state"] == "near_limit"

    duplicate_total = client.post(
        "/api/goals?timezone=UTC",
        headers=identity.app_headers,
        json={
            "name": "重复总目标",
            "month": "2026-05",
            "target_amount_cents": 7000,
        },
    )
    assert duplicate_total.status_code == 409
    assert duplicate_total.json()["error"] == "invalid_request"

    category_goal = client.post(
        "/api/goals?timezone=UTC",
        headers=identity.app_headers,
        json={
            "name": "控制餐饮",
            "month": "2026-05",
            "category": "吃饭",
            "target_amount_cents": 2000,
        },
    )
    assert category_goal.status_code == 201, category_goal.json()
    category_payload = category_goal.json()
    assert category_payload["category"] == "餐饮"
    assert category_payload["spent_amount_cents"] == 1200
    assert category_payload["remaining_amount_cents"] == 800
    assert category_payload["progress_percent"] == 60
    assert category_payload["progress_state"] == "on_track"

    duplicate_category = client.post(
        "/api/goals?timezone=UTC",
        headers=identity.app_headers,
        json={
            "name": "重复餐饮目标",
            "month": "2026-05",
            "category": "餐饮",
            "target_amount_cents": 3000,
        },
    )
    assert duplicate_category.status_code == 409
    assert duplicate_category.json()["error"] == "invalid_request"

    goals = client.get("/api/goals?month=2026-05&timezone=UTC", headers=identity.app_headers)
    assert goals.status_code == 200, goals.json()
    items = goals.json()["items"]
    assert [item["name"] for item in items] == ["本月总支出", "控制餐饮"]
    assert [item["spent_amount_cents"] for item in items] == [4200, 1200]


def test_goals_progress_uses_timezone_and_confirmed_at_fallback(client: TestClient, *, identity) -> None:
    _insert_expense(
        amount_cents=1851,
        merchant="手机时区边界账单",
        category="生活",
        status="confirmed",
        expense_time=None,
        confirmed_at=datetime(2026, 4, 30, 16, 30, tzinfo=UTC),
    )
    goal = client.post(
        "/api/goals?timezone=Asia/Shanghai",
        headers=identity.app_headers,
        json={
            "name": "生活目标",
            "month": "2026-05",
            "category": "生活",
            "target_amount_cents": 2000,
        },
    )
    assert goal.status_code == 201, goal.json()
    public_id = goal.json()["public_id"]
    assert goal.json()["spent_amount_cents"] == 1851
    assert goal.json()["progress_state"] == "near_limit"

    utc_detail = client.get(
        f"/api/goals/{public_id}?timezone=UTC",
        headers=identity.app_headers,
    )
    assert utc_detail.status_code == 200, utc_detail.json()
    assert utc_detail.json()["spent_amount_cents"] == 0
    assert utc_detail.json()["progress_state"] == "not_started"


def test_goals_permissions_and_ledger_isolation(client: TestClient, *, identity) -> None:
    owner_goal = client.post(
        "/api/goals",
        headers=identity.app_headers,
        json={
            "name": "Owner Goal",
            "month": "2026-05",
            "target_amount_cents": 5000,
        },
    )
    assert owner_goal.status_code == 201, owner_goal.json()
    owner_public_id = owner_goal.json()["public_id"]

    gray_goal = client.post(
        "/api/goals",
        headers=identity.gray_app_headers,
        json={
            "name": "Gray Goal",
            "month": "2026-05",
            "target_amount_cents": 6000,
        },
    )
    assert gray_goal.status_code == 201, gray_goal.json()
    gray_public_id = gray_goal.json()["public_id"]

    gray_list = client.get("/api/goals?month=2026-05", headers=identity.gray_app_headers)
    assert gray_list.status_code == 200, gray_list.json()
    assert [item["name"] for item in gray_list.json()["items"]] == ["Gray Goal"]

    gray_reads_owner_goal = client.get(
        f"/api/goals/{owner_public_id}",
        headers=identity.gray_app_headers,
    )
    assert gray_reads_owner_goal.status_code == 404
    assert gray_reads_owner_goal.json()["error"] == "goal_not_found"

    owner_reads_gray_goal = client.get(
        f"/api/goals/{gray_public_id}",
        headers=identity.app_headers,
    )
    assert owner_reads_gray_goal.status_code == 404
    assert owner_reads_gray_goal.json()["error"] == "goal_not_found"

    _set_owner_ledger_role("viewer")
    viewer_read = client.get("/api/goals?month=2026-05", headers=identity.app_headers)
    assert viewer_read.status_code == 200, viewer_read.json()
    assert [item["name"] for item in viewer_read.json()["items"]] == ["Owner Goal"]

    _assert_permission_denied(
        client.post(
            "/api/goals",
            headers=identity.app_headers,
            json={
                "name": "Viewer Write",
                "month": "2026-05",
                "target_amount_cents": 7000,
            },
        ),
        label="viewer goal create",
    )
    _assert_permission_denied(
        client.patch(
            f"/api/goals/{owner_public_id}",
            headers=identity.app_headers,
            json={"name": "Viewer Patch"},
        ),
        label="viewer goal patch",
    )
    _assert_permission_denied(
        client.post(f"/api/goals/{owner_public_id}/archive", headers=identity.app_headers),
        label="viewer goal archive",
    )


def test_goals_update_archive_and_validation(client: TestClient, *, identity) -> None:
    invalid_month = client.post(
        "/api/goals",
        headers=identity.app_headers,
        json={
            "name": "Bad Month",
            "month": "2026-13",
            "target_amount_cents": 1000,
        },
    )
    assert invalid_month.status_code == 422
    assert invalid_month.json()["error"] == "invalid_request"

    invalid_type = client.post(
        "/api/goals",
        headers=identity.app_headers,
        json={
            "name": "Saving Target",
            "month": "2026-05",
            "goal_type": "saving_target",
            "target_amount_cents": 1000,
        },
    )
    assert invalid_type.status_code == 422
    assert invalid_type.json()["error"] == "invalid_request"

    created = client.post(
        "/api/goals",
        headers=identity.app_headers,
        json={
            "name": "餐饮目标",
            "month": "2026-05",
            "category": "餐饮",
            "target_amount_cents": 3000,
        },
    )
    assert created.status_code == 201, created.json()
    public_id = created.json()["public_id"]

    updated = client.patch(
        f"/api/goals/{public_id}",
        headers=identity.app_headers,
        json={
            "name": "全月目标",
            "category": None,
            "target_amount_cents": 5000,
        },
    )
    assert updated.status_code == 200, updated.json()
    assert updated.json()["name"] == "全月目标"
    assert updated.json()["category"] is None
    assert updated.json()["target_amount_cents"] == 5000

    archived = client.post(f"/api/goals/{public_id}/archive", headers=identity.app_headers)
    assert archived.status_code == 200, archived.json()
    assert archived.json()["status"] == "archived"
    assert archived.json()["progress_state"] == "archived"

    hidden = client.get("/api/goals?month=2026-05", headers=identity.app_headers)
    assert hidden.status_code == 200
    assert hidden.json()["items"] == []

    visible = client.get(
        "/api/goals?month=2026-05&include_archived=true",
        headers=identity.app_headers,
    )
    assert visible.status_code == 200
    assert [item["public_id"] for item in visible.json()["items"]] == [public_id]

    archived_patch = client.patch(
        f"/api/goals/{public_id}",
        headers=identity.app_headers,
        json={"name": "不能修改"},
    )
    assert archived_patch.status_code == 409
    assert archived_patch.json()["error"] == "invalid_request"
