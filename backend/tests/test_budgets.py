"""v0.8 budget API contract: dashboard math, ledger isolation, writer guard."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Budget, BudgetCategory, LedgerMember, RecurringItem
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


def _seed_recurring(
    *,
    tenant_id: str = "owner",
    merchant_key: str = "netflix",
    merchant_name: str = "Netflix",
    baseline_amount_cents: int = 6800,
    created_at: datetime | None = None,
    status: str = "active",
    paused_at: datetime | None = None,
    archived_at: datetime | None = None,
) -> None:
    now = created_at or now_utc()
    with SessionLocal() as db:
        db.add(
            RecurringItem(
                tenant_id=tenant_id,
                merchant_key=merchant_key,
                merchant_name=merchant_name,
                frequency="monthly",
                baseline_amount_cents=baseline_amount_cents,
                last_amount_cents=baseline_amount_cents,
                occurrence_count=3,
                last_seen_at=now,
                status=status,
                confidence="high",
                source="candidate",
                created_at=now,
                updated_at=now,
                paused_at=paused_at,
                archived_at=archived_at,
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


def test_monthly_budget_dashboard_uses_confirmed_spend_fixed_and_exclusions(
    client: TestClient, *, identity,
) -> None:
    # Anchor created_at to the test's target month (2026-05). The default
    # ``now_utc()`` makes this test wall-clock-dependent: once now_utc()
    # crosses into 2026-06, the recurring's created_at falls outside the
    # "2026-05" UTC end bound and gets filtered out (fixed_amount_cents
    # becomes 0). Same anti-pattern as test_budget_advise_endpoint's
    # _current_month() / _seed_minimal_data() — fix at the call site,
    # matching test_monthly_budget_fixed_spend_uses_recurring_month_membership
    # which already passes explicit created_at dates.
    _seed_recurring(
        baseline_amount_cents=6800,
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    _seed_recurring(
        tenant_id="tester_1",
        merchant_key="gray-recurring",
        merchant_name="Gray Recurring",
        baseline_amount_cents=9900,
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    _manual_expense(
        client,
        headers=identity.app_headers,
        amount_cents=12000,
        merchant="五月餐饮",
        category="餐饮",
        expense_time="2026-05-05T12:00:00Z",
    )
    _manual_expense(
        client,
        headers=identity.app_headers,
        amount_cents=3500,
        merchant="五月交通",
        category="交通",
        expense_time="2026-05-06T12:00:00Z",
    )
    _manual_expense(
        client,
        headers=identity.app_headers,
        amount_cents=9900,
        merchant="医保报销",
        category="医疗",
        expense_time="2026-05-07T12:00:00Z",
    )
    _manual_expense(
        client,
        headers=identity.app_headers,
        amount_cents=7777,
        merchant="上月餐饮",
        category="餐饮",
        expense_time="2026-04-30T12:00:00Z",
    )
    _manual_expense(
        client,
        headers=identity.gray_app_headers,
        amount_cents=7777,
        merchant="灰度餐饮",
        category="餐饮",
        expense_time="2026-05-05T12:00:00Z",
    )

    response = client.put(
        "/api/budgets/monthly/2026-05?timezone=UTC",
        headers=identity.app_headers,
        json={
            "total_amount_cents": 100000,
            "non_monthly_amount_cents": 15000,
            "rollover_amount_cents": 5000,
            "excluded_categories": ["医疗"],
            "category_budgets": [
                {"category": "餐饮", "amount_cents": 10000},
                {"category": "交通", "amount_cents": 5000},
            ],
        },
    )
    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["ledger_id"] == "owner"
    assert payload["configured"] is True
    assert payload["fixed_amount_cents"] == 6800
    assert payload["flex_budget_cents"] == 83200
    assert payload["spent_amount_cents"] == 15500
    assert payload["excluded_amount_cents"] == 9900
    assert payload["remaining_amount_cents"] == 89500
    assert payload["overspent_amount_cents"] == 0
    assert payload["excluded_breakdown"] == [{"category": "医疗", "amount_cents": 9900, "count": 1}]
    assert payload["category_budgets"] == [
        {
            "category": "交通",
            "amount_cents": 5000,
            "spent_amount_cents": 3500,
            "remaining_amount_cents": 1500,
            "overspent_amount_cents": 0,
        },
        {
            "category": "餐饮",
            "amount_cents": 10000,
            "spent_amount_cents": 12000,
            "remaining_amount_cents": -2000,
            "overspent_amount_cents": 2000,
        },
    ]

    gray = client.get("/api/budgets/monthly?month=2026-05&timezone=UTC", headers=identity.gray_app_headers)
    assert gray.status_code == 200, gray.json()
    gray_payload = gray.json()
    assert gray_payload["ledger_id"] == "tester_1"
    assert gray_payload["configured"] is False
    assert gray_payload["total_amount_cents"] == 0
    assert gray_payload["fixed_amount_cents"] == 9900
    assert gray_payload["spent_amount_cents"] == 7777
    assert gray_payload["remaining_amount_cents"] == 0
    assert gray_payload["overspent_amount_cents"] == 0
    assert gray_payload["category_budgets"] == []


def test_monthly_budget_fixed_spend_uses_recurring_month_membership(
    client: TestClient, *, identity,
) -> None:
    _seed_recurring(
        merchant_key="may-active",
        merchant_name="May Active",
        baseline_amount_cents=5000,
        created_at=datetime(2026, 5, 10, tzinfo=UTC),
    )
    _seed_recurring(
        merchant_key="june-new",
        merchant_name="June New",
        baseline_amount_cents=9000,
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    _seed_recurring(
        merchant_key="april-archived",
        merchant_name="April Archived",
        baseline_amount_cents=3000,
        created_at=datetime(2026, 4, 1, tzinfo=UTC),
        status="archived",
        archived_at=datetime(2026, 4, 25, tzinfo=UTC),
    )

    may = client.get("/api/budgets/monthly?month=2026-05&timezone=UTC", headers=identity.app_headers)
    assert may.status_code == 200, may.json()
    assert may.json()["fixed_amount_cents"] == 5000

    june = client.get("/api/budgets/monthly?month=2026-06&timezone=UTC", headers=identity.app_headers)
    assert june.status_code == 200, june.json()
    assert june.json()["fixed_amount_cents"] == 14000


def test_monthly_budget_upsert_replaces_category_rows_without_duplicates(
    client: TestClient, *, identity,
) -> None:
    first = client.put(
        "/api/budgets/monthly/2026-05",
        headers=identity.app_headers,
        json={
            "total_amount_cents": 80000,
            "excluded_categories": ["医疗", "医疗"],
            "category_budgets": [
                {"category": "餐饮", "amount_cents": 20000},
                {"category": "交通", "amount_cents": 6000},
            ],
        },
    )
    assert first.status_code == 200, first.json()

    second = client.put(
        "/api/budgets/monthly/2026-05",
        headers=identity.app_headers,
        json={
            "total_amount_cents": 90000,
            "non_monthly_amount_cents": 12000,
            "rollover_amount_cents": -3000,
            "excluded_categories": ["医疗", "报销"],
            "category_budgets": [
                {"category": "餐饮", "amount_cents": 25000},
            ],
        },
    )
    assert second.status_code == 200, second.json()
    payload = second.json()
    assert payload["total_amount_cents"] == 90000
    assert payload["rollover_amount_cents"] == -3000
    assert payload["excluded_categories"] == ["医疗", "报销"]
    assert payload["category_budgets"] == [
        {
            "category": "餐饮",
            "amount_cents": 25000,
            "spent_amount_cents": 0,
            "remaining_amount_cents": 25000,
            "overspent_amount_cents": 0,
        }
    ]

    with SessionLocal() as db:
        budget_count = db.scalar(
            select(func.count(Budget.id))
            .where(Budget.tenant_id == "owner")
            .where(Budget.month == "2026-05")
        )
        category_count = db.scalar(
            select(func.count(BudgetCategory.id))
            .where(BudgetCategory.tenant_id == "owner")
            .where(BudgetCategory.month == "2026-05")
        )
    assert budget_count == 1
    assert category_count == 1


def test_member_can_upsert_budget_but_viewer_can_only_read(client: TestClient, *, identity) -> None:
    _set_owner_ledger_role("member")
    member_response = client.put(
        "/api/budgets/monthly/2026-05",
        headers=identity.app_headers,
        json={"total_amount_cents": 50000},
    )
    assert member_response.status_code == 200, member_response.json()

    _set_owner_ledger_role("viewer")
    viewer_write = client.put(
        "/api/budgets/monthly/2026-05",
        headers=identity.app_headers,
        json={"total_amount_cents": 60000},
    )
    _assert_permission_denied(viewer_write, label="viewer budget update")

    viewer_read = client.get("/api/budgets/monthly?month=2026-05", headers=identity.app_headers)
    assert viewer_read.status_code == 200, viewer_read.json()
    assert viewer_read.json()["total_amount_cents"] == 50000


def test_budget_rejects_invalid_month_and_duplicate_normalized_categories(
    client: TestClient, *, identity,
) -> None:
    invalid_month = client.put(
        "/api/budgets/monthly/2026-13",
        headers=identity.app_headers,
        json={"total_amount_cents": 50000},
    )
    assert invalid_month.status_code == 422, invalid_month.json()
    assert invalid_month.json()["error"] == "invalid_request"

    duplicate_category = client.put(
        "/api/budgets/monthly/2026-05",
        headers=identity.app_headers,
        json={
            "total_amount_cents": 50000,
            "category_budgets": [
                {"category": "吃饭", "amount_cents": 10000},
                {"category": "餐饮", "amount_cents": 12000},
            ],
        },
    )
    assert duplicate_category.status_code == 422, duplicate_category.json()
    assert duplicate_category.json()["error"] == "invalid_request"


def test_budget_rejects_unbounded_month_without_persisting(client: TestClient, *, identity) -> None:
    response = client.put(
        "/api/budgets/monthly/9999-12?timezone=UTC",
        headers=identity.app_headers,
        json={"total_amount_cents": 50000},
    )
    assert response.status_code == 422, response.json()
    assert response.json()["error"] == "invalid_request"

    with SessionLocal() as db:
        budget_count = db.scalar(
            select(func.count(Budget.id))
            .where(Budget.tenant_id == "owner")
            .where(Budget.month == "9999-12")
        )
    assert budget_count == 0
