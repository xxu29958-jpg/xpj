"""ADR-0051 current-ledger recycle-bin API + /web coverage."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import (
    Budget,
    CategoryPreference,
    CategoryRule,
    Goal,
    LedgerMember,
    MonthlyIncomePlan,
    RecurringItem,
)
from app.schemas import BudgetCategoryRequest, BudgetMonthlyUpdateRequest
from app.services.budget_service import archive_monthly_budget, upsert_monthly_budget
from app.services.category_preference_service import (
    delete_category_preference,
    ensure_category_preference_for_name,
)
from app.services.classify_service import create_rule, delete_rule
from app.services.goal_service import archive_goal
from app.services.income_plan_service import archive_income_plan, create_income_plan
from app.services.recurring_service import archive_recurring_item
from app.services.soft_delete_policy import recycle_bin_retention_delta
from app.services.time_service import now_utc
from tests._infra.currency import activate_test_currency_authority


def _seed_archived_income(
    *,
    tenant_id: str = "owner",
    label: str = "回收站收入",
    amount_cents: int = 123400,
) -> tuple[str, int]:
    with SessionLocal() as db:
        plan = create_income_plan(
            db,
            tenant_id=tenant_id,
            label=label,
            source_type="salary",
            amount_cents=amount_cents,
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


def _seed_archived_jpy_money_facts() -> str:
    """Seed read-only recycle-bin facts after an explicit JPY adoption."""

    with SessionLocal() as db:
        activate_test_currency_authority(db, "JPY")
        timestamp = now_utc()
        income = MonthlyIncomePlan(
            tenant_id="owner", label="JPY收入",
            frequency="one_time", income_month="2026-06",
            amount_cents=5000,
            pay_day=28, status="archived", archived_at=timestamp,
        )
        budget = Budget(
            tenant_id="owner", month="2026-07", total_amount_cents=66000, archived_at=timestamp
        )
        db.add_all([income, budget])
        db.commit()
        return "2026-07"


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


def _make_viewer_ledger(client: TestClient, *, identity) -> str:
    response = client.post(
        "/api/ledgers",
        headers=identity.admin_headers,
        json={"name": "recycle-workbench-viewer"},
    )
    assert response.status_code == 201, response.json()
    ledger_id = response.json()["ledger_id"]
    with SessionLocal() as db:
        member = db.scalar(
            select(LedgerMember).where(LedgerMember.ledger_id == ledger_id).limit(1)
        )
        assert member is not None
        member.role = "viewer"
        db.commit()
    return ledger_id


def test_web_recycle_bin_workbench_structure_owner(
    web_client: TestClient, *, identity
) -> None:
    """C5b-1 工作台化结构钉：五域 IA 面包屑 + 产品表格 + owner 恢复表单/OCC 字段。"""
    _seed_archived_income(label="工作台结构收入")

    response = web_client.get("/web/recycle-bin")

    assert response.status_code == 200
    body = response.text
    # 五域 IA：回收站仍归流水域，但 section 父级已经收口到资料库 hub。
    assert 'aria-label="面包屑"' in body
    assert 'class="rb-breadcrumb-parent" href="/web/library?ledger_id=owner">资料库</a>' in body
    # 工作台面板 + 产品表格 (取代旧 dt-card KPI + dt-table)。
    assert 'aria-label="可恢复项目"' in body
    assert 'class="product-table"' in body
    # ≤720px 表头留在无障碍树 (PR#252 P2 钉)：th 文本由 rb-sr-only 视觉隐藏，
    # 不再 display:none 整个 thead —— 屏幕阅读器保留 保留状态/操作 列关联。
    assert '<th><span class="rb-sr-only">保留状态</span></th>' in body
    assert '<th><span class="rb-sr-only">操作</span></th>' in body
    # owner 可写：恢复表单与 OCC 隐藏字段在；行身份锚在。
    assert 'action="/web/recycle-bin/restore"' in body
    assert 'name="expected_row_version"' in body
    assert 'data-restore-key="income_plan:' in body


def test_web_recycle_bin_workbench_viewer_readonly(
    web_client: TestClient, *, identity
) -> None:
    """C5b-1：viewer 只读语义不破 (无恢复表单)；空态给同域 (流水) 行动链接。"""
    ledger_id = _make_viewer_ledger(web_client, identity=identity)

    response = web_client.get(f"/web/recycle-bin?ledger_id={ledger_id}")

    assert response.status_code == 200
    body = response.text
    assert 'action="/web/recycle-bin/restore"' not in body
    assert ">恢复</button>" not in body
    assert "只读角色可以查看回收站" in body
    # 空账本 → 空态：标题 + 同域 (分类/商家/标签) 行动链接。
    assert "回收站是空的" in body
    assert f'href="/web/categories?ledger_id={ledger_id}"' in body


def _seed_archived_goal_for_label() -> None:
    with SessionLocal() as db:
        now = now_utc()
        goal = Goal(
            tenant_id="owner",
            name="回收站目标",
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
        archive_goal(
            db,
            tenant_id="owner",
            public_id=goal.public_id,
            timezone_name="Asia/Shanghai",
        )


def _seed_archived_recurring_for_label() -> None:
    with SessionLocal() as db:
        now = now_utc()
        item = RecurringItem(
            tenant_id="owner",
            merchant_key="recycle-currency-recurring",
            merchant_name="回收站固定支出",
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
        archive_recurring_item(db, tenant_id="owner", public_id=item.public_id)


@pytest.mark.currency_binding_unbound
def test_recycle_bin_amount_labels_follow_jpy_home_zero_fraction(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    identity,
) -> None:
    """C5b-3: JPY home → 回收站金额按零小数渲染（¥5,000 而非 ¥50.00），
    收入/预算混合行同一规则（行无币种列，金额即 home 币种 minor units）。"""
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    get_settings.cache_clear()
    try:
        month = _seed_archived_jpy_money_facts()

        response = client.get("/api/recycle-bin", headers=identity.app_headers)

        assert response.status_code == 200
        details = {item["title"]: item["detail"] for item in response.json()["items"]}
        assert "¥5,000" in details["JPY收入"]
        assert "50.00" not in details["JPY收入"]
        assert "¥66,000" in details[f"{month} 月度预算"]
        assert "660.00" not in details[f"{month} 月度预算"]
    finally:
        get_settings.cache_clear()


def test_recycle_bin_amount_labels_follow_cny_home_two_fraction(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    identity,
) -> None:
    """C5b-3: CNY home → 两位小数；收入/目标/固定支出混合行都走 divmod 标签。"""
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "CNY")
    get_settings.cache_clear()
    try:
        _seed_archived_income(label="两位小数收入", amount_cents=5000)
        _seed_archived_goal_for_label()
        _seed_archived_recurring_for_label()

        response = client.get("/api/recycle-bin", headers=identity.app_headers)

        assert response.status_code == 200
        details = {item["title"]: item["detail"] for item in response.json()["items"]}
        assert "¥50.00" in details["两位小数收入"]
        assert "¥100.00" in details["回收站目标"]
        assert "¥68.00" in details["回收站固定支出"]
    finally:
        get_settings.cache_clear()


def test_recycle_bin_hides_rows_beyond_retention_window(
    client: TestClient,
    *,
    identity,
) -> None:
    """C5b-3: 超窗行不进列表；窗内金额行的币种标签不受影响。"""
    _seed_archived_income(label="窗内收入", amount_cents=5000)
    preference_id, _row_version = _seed_deleted_category_preference()
    with SessionLocal() as db:
        preference = db.scalar(
            select(CategoryPreference).where(
                CategoryPreference.public_id == preference_id
            )
        )
        assert preference is not None
        preference.deleted_at = (
            now_utc() - recycle_bin_retention_delta() - timedelta(days=1)
        )
        db.commit()

    response = client.get("/api/recycle-bin", headers=identity.app_headers)

    assert response.status_code == 200
    items = response.json()["items"]
    titles = [item["title"] for item in items]
    assert "窗内收入" in titles
    assert "回收分类" not in titles
    income_detail = next(
        item["detail"] for item in items if item["title"] == "窗内收入"
    )
    assert "¥50.00" in income_detail
