"""Owner Console unified recycle-bin coverage (ADR-0051 first slice)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import Budget, BudgetCategory, CategoryRule, Goal, MonthlyIncomePlan, RecurringItem
from app.routes.owner_console import _require_local
from app.schemas import BudgetCategoryRequest, BudgetMonthlyUpdateRequest
from app.services.budget_service import archive_monthly_budget, upsert_monthly_budget
from app.services.classify_service import create_rule, delete_rule, find_rule_for_tenant
from app.services.goal_service import archive_goal
from app.services.income_plan_service import archive_income_plan, create_income_plan
from app.services.ledger_service import archive_ledger
from app.services.merchant_alias_service import create_merchant_alias, delete_merchant_alias
from app.services.owner_console_service import get_owner_account_id
from app.services.recurring_service import archive_recurring_item
from app.services.time_service import now_utc


@pytest.fixture()
def local_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_require_local, None)


def _owner_id() -> int:
    with SessionLocal() as db:
        owner_id = get_owner_account_id(db)
        assert owner_id is not None
        return owner_id


def _seed_archived_income() -> tuple[str, int]:
    with SessionLocal() as db:
        plan = create_income_plan(
            db,
            tenant_id="owner",
            label="收入回收测试",
            source_type="salary",
            amount_cents=123400,
            pay_day=28,
            frequency="one_time",
            income_month="2026-06",
        )
        archived = archive_income_plan(
            db,
            tenant_id="owner",
            public_id=plan.public_id,
            expected_row_version=plan.row_version,
        )
        return archived.public_id, archived.row_version


def _seed_archived_budget() -> tuple[str, int]:
    with SessionLocal() as db:
        budget = upsert_monthly_budget(
            db,
            tenant_id="owner",
            month="2026-07",
            payload=BudgetMonthlyUpdateRequest(
                total_amount_cents=88000,
                category_budgets=[
                    BudgetCategoryRequest(category="餐饮", amount_cents=22000)
                ],
            ),
        )
        archived = archive_monthly_budget(
            db,
            tenant_id="owner",
            month=budget.month,
            expected_row_version=budget.row_version or 1,
        )
        return archived.month, archived.row_version


def _seed_archived_recurring() -> tuple[str, int]:
    with SessionLocal() as db:
        now = now_utc()
        item = RecurringItem(
            tenant_id="owner",
            merchant_key="recurring-recycle-test",
            merchant_name="固定支出回收测试",
            frequency="monthly",
            baseline_amount_cents=6800,
            last_amount_cents=6800,
            occurrence_count=3,
            status="active",
            confidence="high",
            source="candidate",
            created_at=now,
            updated_at=now,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        archived = archive_recurring_item(
            db, tenant_id="owner", public_id=item.public_id
        )
        return archived.public_id, archived.row_version


def _seed_archived_goal() -> tuple[str, int]:
    with SessionLocal() as db:
        now = now_utc()
        goal = Goal(
            tenant_id="owner",
            name="目标回收测试",
            goal_type="spending_limit",
            period="monthly",
            month="2026-06",
            category="餐饮",
            target_amount_cents=10000,
            status="active",
            created_at=now,
            updated_at=now,
        )
        db.add(goal)
        db.commit()
        db.refresh(goal)
        archived = archive_goal(
            db,
            tenant_id="owner",
            public_id=goal.public_id,
            timezone_name="Asia/Shanghai",
        )
        return archived.public_id, archived.row_version


def _seed_deleted_rule() -> int:
    with SessionLocal() as db:
        rule = create_rule(
            db,
            tenant_id="owner",
            keyword="规则回收测试",
            category="餐饮",
            enabled=True,
            priority=10,
        )
        rule_id = rule.id
        delete_rule(db, rule, expected_row_version=rule.row_version)
        return rule_id


def _age_deleted_rule_past_undo_window(rule_id: int) -> None:
    with SessionLocal() as db:
        rule = db.scalar(select(CategoryRule).where(CategoryRule.id == rule_id))
        assert rule is not None
        rule.deleted_at = now_utc() - timedelta(minutes=10)
        db.commit()


def _seed_deleted_alias() -> str:
    with SessionLocal() as db:
        alias = create_merchant_alias(
            db,
            tenant_id="owner",
            canonical_merchant="标准商家回收测试",
            alias="别名回收测试",
        )
        public_id = alias.public_id
        delete_merchant_alias(db, alias, expected_row_version=alias.row_version)
        return public_id


def test_owner_recycle_bin_lists_supported_items(
    local_client: TestClient, *, identity
) -> None:
    owner_id = _owner_id()
    with SessionLocal() as db:
        archive_ledger(db, ledger_id="tester_1", actor_account_id=owner_id)
    _seed_archived_income()
    _seed_archived_budget()
    _seed_archived_recurring()
    _seed_archived_goal()
    _seed_deleted_rule()
    _seed_deleted_alias()

    response = local_client.get("/owner/recycle-bin")

    assert response.status_code == 200
    body = response.text
    assert "回收站" in body
    assert "灰度用户1" in body
    assert "收入回收测试" in body
    assert "2026-07 月度预算" in body
    assert "固定支出回收测试" in body
    assert "目标回收测试" in body
    assert "规则回收测试" in body
    assert "别名回收测试" in body
    assert "30 天内可恢复" in body
    assert "长期保留" in body


def test_owner_recycle_bin_restores_archived_income(
    local_client: TestClient, *, identity
) -> None:
    public_id, row_version = _seed_archived_income()

    response = local_client.post(
        "/owner/recycle-bin/restore",
        data={
            "kind": "income_plan",
            "ledger_id": "owner",
            "resource_id": public_id,
            "expected_row_version": str(row_version),
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    with SessionLocal() as db:
        status = db.scalar(
            select(MonthlyIncomePlan.status).where(
                MonthlyIncomePlan.public_id == public_id
            )
        )
    assert status == "active"


def test_owner_recycle_bin_restores_archived_budget(
    local_client: TestClient, *, identity
) -> None:
    month, row_version = _seed_archived_budget()

    response = local_client.post(
        "/owner/recycle-bin/restore",
        data={
            "kind": "monthly_budget",
            "ledger_id": "owner",
            "resource_id": month,
            "expected_row_version": str(row_version),
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    with SessionLocal() as db:
        budget = db.scalar(
            select(Budget).where(Budget.tenant_id == "owner").where(Budget.month == month)
        )
        assert budget is not None
        assert budget.archived_at is None
        category_row = db.scalar(
            select(BudgetCategory)
            .where(BudgetCategory.tenant_id == "owner")
            .where(BudgetCategory.month == month)
        )
    assert category_row is not None


def test_owner_recycle_bin_restores_deleted_rule(
    local_client: TestClient, *, identity
) -> None:
    rule_id = _seed_deleted_rule()
    _age_deleted_rule_past_undo_window(rule_id)

    response = local_client.post(
        "/owner/recycle-bin/restore",
        data={
            "kind": "category_rule",
            "ledger_id": "owner",
            "resource_id": str(rule_id),
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    with SessionLocal() as db:
        assert find_rule_for_tenant(db, tenant_id="owner", rule_id=rule_id) is not None


def test_owner_recycle_bin_remote_returns_403(client: TestClient, *, identity) -> None:
    assert client.get("/owner/recycle-bin").status_code == 403
    assert (
        client.post(
            "/owner/recycle-bin/restore",
            data={"kind": "income_plan", "ledger_id": "owner", "resource_id": "x"},
        ).status_code
        == 403
    )
