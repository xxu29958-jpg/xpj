"""ADR-0051 current-ledger recycle-bin API + /web coverage."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Budget, CategoryPreference, CategoryRule, MonthlyIncomePlan
from app.schemas import BudgetCategoryRequest, BudgetMonthlyUpdateRequest
from app.services.budget_service import archive_monthly_budget, upsert_monthly_budget
from app.services.category_preference_service import (
    delete_category_preference,
    ensure_category_preference_for_name,
)
from app.services.classify_service import create_rule, delete_rule
from app.services.income_plan_service import archive_income_plan, create_income_plan
from app.services.time_service import now_utc


def _seed_archived_income(
    *,
    tenant_id: str = "owner",
    label: str = "回收站收入",
) -> tuple[str, int]:
    with SessionLocal() as db:
        plan = create_income_plan(
            db,
            tenant_id=tenant_id,
            label=label,
            source_type="salary",
            amount_cents=123400,
            pay_day=28,
            frequency="one_time",
            income_month="2026-06",
        )
        archived = archive_income_plan(
            db,
            tenant_id=tenant_id,
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
                total_amount_cents=66000,
                category_budgets=[
                    BudgetCategoryRequest(category="交通", amount_cents=12000)
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


def _seed_deleted_category_preference() -> tuple[str, int]:
    with SessionLocal() as db:
        item = ensure_category_preference_for_name(
            db, tenant_id="owner", name="回收分类"
        )
        assert item is not None
        db.flush()
        public_id = item.public_id
        deleted = delete_category_preference(
            db,
            tenant_id="owner",
            public_id=public_id,
            expected_row_version=item.row_version,
        )
        return public_id, deleted.row_version


def _seed_deleted_rule() -> int:
    with SessionLocal() as db:
        rule = create_rule(
            db,
            tenant_id="owner",
            keyword="回收站规则",
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


def test_recycle_bin_api_lists_current_ledger_only(
    client: TestClient, *, identity
) -> None:
    _seed_archived_income(label="本账本收入")
    _seed_archived_income(tenant_id="tester_1", label="其它账本收入")
    _seed_deleted_rule()

    response = client.get("/api/recycle-bin", headers=identity.app_headers)

    assert response.status_code == 200
    body = response.json()
    titles = [item["title"] for item in body["items"]]
    assert "本账本收入" in titles
    assert "回收站规则" in titles
    assert "其它账本收入" not in titles
    assert body["short_window_count"] == 1


def test_recycle_bin_api_restores_deleted_rule_after_undo_window(
    client: TestClient, *, identity
) -> None:
    rule_id = _seed_deleted_rule()
    _age_deleted_rule_past_undo_window(rule_id)

    listed = client.get("/api/recycle-bin", headers=identity.app_headers)

    assert listed.status_code == 200
    assert "回收站规则" in [item["title"] for item in listed.json()["items"]]
    assert any(
        item["retention_label"] == "30 天内可恢复" for item in listed.json()["items"]
    )

    restored = client.post(
        "/api/recycle-bin/restore",
        headers=identity.app_headers,
        json={"kind": "category_rule", "resource_id": str(rule_id)},
    )

    assert restored.status_code == 200
    with SessionLocal() as db:
        deleted_at = db.scalar(
            select(CategoryRule.deleted_at).where(CategoryRule.id == rule_id)
        )
    assert deleted_at is None


def test_recycle_bin_api_restores_archived_income(
    client: TestClient, *, identity
) -> None:
    public_id, row_version = _seed_archived_income()

    response = client.post(
        "/api/recycle-bin/restore",
        headers=identity.app_headers,
        json={
            "kind": "income_plan",
            "resource_id": public_id,
            "expected_row_version": row_version,
        },
    )

    assert response.status_code == 200
    assert response.json()["message"] == "收入记录已恢复。"
    with SessionLocal() as db:
        status = db.scalar(
            select(MonthlyIncomePlan.status).where(
                MonthlyIncomePlan.public_id == public_id
            )
        )
    assert status == "active"


def test_recycle_bin_api_restores_deleted_category_preference(
    client: TestClient, *, identity
) -> None:
    public_id, row_version = _seed_deleted_category_preference()

    response = client.post(
        "/api/recycle-bin/restore",
        headers=identity.app_headers,
        json={
            "kind": "category_preference",
            "resource_id": public_id,
            "expected_row_version": row_version,
        },
    )

    assert response.status_code == 200
    assert response.json()["message"] == "分类已恢复。"
    with SessionLocal() as db:
        deleted_at = db.scalar(
            select(CategoryPreference.deleted_at).where(
                CategoryPreference.public_id == public_id
            )
        )
    assert deleted_at is None


def test_web_recycle_bin_lists_and_restores_income(
    web_client: TestClient, *, identity
) -> None:
    public_id, row_version = _seed_archived_income(label="网页回收收入")

    list_response = web_client.get("/web/recycle-bin")

    assert list_response.status_code == 200
    body = list_response.text
    assert "回收站" in body
    assert "网页回收收入" in body
    assert f'value="{row_version}"' in body

    restore_response = web_client.post(
        "/web/recycle-bin/restore",
        data={
            "kind": "income_plan",
            "resource_id": public_id,
            "expected_row_version": str(row_version),
        },
        follow_redirects=False,
    )

    assert restore_response.status_code == 303
    with SessionLocal() as db:
        status = db.scalar(
            select(MonthlyIncomePlan.status).where(
                MonthlyIncomePlan.public_id == public_id
            )
        )
    assert status == "active"


def test_web_recycle_bin_lists_and_restores_budget(
    web_client: TestClient, *, identity
) -> None:
    month, row_version = _seed_archived_budget()

    list_response = web_client.get("/web/recycle-bin")

    assert list_response.status_code == 200
    assert f"{month} 月度预算" in list_response.text
    assert f'value="{row_version}"' in list_response.text

    restore_response = web_client.post(
        "/web/recycle-bin/restore",
        data={
            "kind": "monthly_budget",
            "resource_id": month,
            "expected_row_version": str(row_version),
        },
        follow_redirects=False,
    )

    assert restore_response.status_code == 303
    with SessionLocal() as db:
        archived_at = db.scalar(
            select(Budget.archived_at)
            .where(Budget.tenant_id == "owner")
            .where(Budget.month == month)
        )
    assert archived_at is None
