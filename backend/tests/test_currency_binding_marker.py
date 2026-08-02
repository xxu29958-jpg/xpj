"""Persisted currency authority and confirm double-gate regression tests.

覆盖：旧 AppMeta 权威退役、持久化绑定漂移、旧写者升级门、
RepaymentDraft 事实集与 confirm 冻结币种比对。
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.c07_money_facts_contract import INSTALLATION_HOME_CURRENCY_KEY
from app.config import get_settings
from app.database import SessionLocal
from app.errors import AppError
from app.models import Debt, Expense
from app.schemas import BudgetMonthlyUpdateRequest, GoalCreateRequest, RecurringCandidateConfirmRequest
from app.services.app_meta_service import get_value
from app.services.budget_service import upsert_monthly_budget
from app.services.currency_binding_service import (
    assert_currency_binding_consistent,
    get_capability,
    resolve_write_capability,
)
from app.services.debt_service._repayment_draft_confirm import confirm_repayment_draft
from app.services.goal_service import create_goal
from app.services.income_plan_service import create_income_plan
from app.services.recurring_candidate_confirmation_service import (
    _create_recurring_item_from_candidate,
    _RecurringCandidateMatch,
)
from tests.test_debt_binding_drift import (
    _create_cny_debt,
    _idem_headers,
    _owner_account_id,
)

pytestmark = pytest.mark.currency_binding_unbound


def _seed_cny_expense_fact_row() -> None:
    with SessionLocal() as db:
        resolve_write_capability(db)
        db.add(Expense(tenant_id="owner", home_currency_code="CNY"))
        db.commit()


def test_jpy_fresh_install_legacy_writer_requires_upgrade(monkeypatch) -> None:
    # C02 不伪造 C03 的客户端版本三元组：旧写者对非 CNY 首笔写入
    # fail closed，且不得恢复 AppMeta 作为绑定权威。
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    get_settings.cache_clear()
    try:
        with SessionLocal() as db:
            with pytest.raises(AppError) as excinfo:
                create_income_plan(
                    db,
                    tenant_id="owner",
                    label="工资",
                    source_type="salary",
                    amount_cents=1200,
                    pay_day=10,
                )
            assert excinfo.value.error == "client_upgrade_required"
            assert get_capability(db).state == "EMPTY"
            assert get_value(db, INSTALLATION_HOME_CURRENCY_KEY) is None
    finally:
        monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
        get_settings.cache_clear()


def test_cny_first_fact_claims_persisted_binding_without_legacy_marker() -> None:
    # 新装首笔 CNY 事实与持久化权威同事务确立；旧 AppMeta 不再自愈。
    with SessionLocal() as db:
        create_income_plan(
            db,
            tenant_id="owner",
            label="工资",
            source_type="salary",
            amount_cents=1_000_000,
            pay_day=10,
        )
        capability = get_capability(db)
        assert capability.state == "ACTIVE"
        assert capability.home_currency_code == "CNY"
        assert get_value(db, INSTALLATION_HOME_CURRENCY_KEY) is None


def test_persisted_binding_disagreeing_with_env_rejects(monkeypatch) -> None:
    # 持久化绑定优先于运行环境；环境漂移必须 fail closed。
    with SessionLocal() as db:
        resolve_write_capability(db)
        db.commit()
        monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
        get_settings.cache_clear()
        try:
            with pytest.raises(AppError) as excinfo:
                assert_currency_binding_consistent(db, "JPY")
            assert excinfo.value.error == "currency_binding_configuration_drift"
        finally:
            monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
            get_settings.cache_clear()


def test_unbound_write_services_gated_under_drift(client: TestClient, monkeypatch, *, identity) -> None:
    # R13-2：CNY 事实 + env=JPY 时，budget/goal/income 三个无绑定写服务各 409（此前
    # 完全无门：漂移下绑定写全 409 但规划写按 env 口径照过）。
    _create_cny_debt(client, identity)
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    get_settings.cache_clear()
    try:
        with SessionLocal() as db:
            with pytest.raises(AppError) as budget_exc:
                upsert_monthly_budget(
                    db,
                    tenant_id="owner",
                    month="2026-07",
                    payload=BudgetMonthlyUpdateRequest(total_amount_cents=1200),
                )
            assert budget_exc.value.error == "currency_binding_configuration_drift"
            with pytest.raises(AppError) as goal_exc:
                create_goal(
                    db,
                    tenant_id="owner",
                    payload=GoalCreateRequest(
                        name="本月外卖",
                        month="2026-07",
                        target_amount_cents=1200,
                    ),
                )
            assert goal_exc.value.error == "currency_binding_configuration_drift"
            with pytest.raises(AppError) as income_exc:
                create_income_plan(
                    db,
                    tenant_id="owner",
                    label="工资",
                    source_type="salary",
                    amount_cents=1200,
                    pay_day=10,
                )
            assert income_exc.value.error == "currency_binding_configuration_drift"
    finally:
        monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
        get_settings.cache_clear()


def test_first_binding_rejected_when_legacy_cny_draft_exists(client: TestClient, monkeypatch, *, identity) -> None:
    # R13-8a 空库四步序列：CNY 环境捕获草稿 → env 翻 JPY → 首笔 JPY 债必须被拒
    # （RepaymentDraft 已入 drift 事实集，否则 CNY 分整数将按 JPY 折叠）。
    response = client.post(
        "/api/repayment-drafts",
        headers=identity.app_headers,
        json={"source": "alipay", "amount_cents": 120000},
    )
    assert response.status_code == 201, response.json()
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    get_settings.cache_clear()
    try:
        created = client.post(
            "/api/debts",
            headers=_idem_headers(identity.app_headers),
            json={
                "direction": "i_owe",
                "counterparty_type": "external",
                "counterparty_label": "房东",
                "principal_amount_cents": 1200,
            },
        )
        assert created.status_code == 409, created.json()
        assert created.json()["error"] == "currency_binding_configuration_drift"
    finally:
        monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
        get_settings.cache_clear()


def test_confirm_rejected_when_draft_currency_mismatches_debt(client: TestClient, monkeypatch, *, identity) -> None:
    # R13-8b：草稿冻结 CNY 分、目标 debt 冻结 JPY（ORM 直种绕过建债门）→ confirm 拒；
    # 比对按两冻结口径，不让 CNY 分整数被当 JPY minor 折叠。
    response = client.post(
        "/api/repayment-drafts",
        headers=identity.app_headers,
        json={"source": "alipay", "amount_cents": 120000},
    )
    assert response.status_code == 201, response.json()
    draft_public_id = response.json()["public_id"]
    with SessionLocal() as db:
        resolve_write_capability(db)
        owner_account_id = _owner_account_id()
        jpy_debt = Debt(
            tenant_id="owner",
            owner_account_id=owner_account_id,
            created_by_account_id=owner_account_id,
            direction="i_owe",
            counterparty_type="external",
            counterparty_account_id=None,
            principal_amount_cents=50000,
            home_currency_code="JPY",
            status="open",
            source_type="manual",
            source_id=None,
        )
        db.add(jpy_debt)
        db.commit()
        with pytest.raises(AppError) as excinfo:
            confirm_repayment_draft(
                db,
                tenant_id="owner",
                actor_account_id=owner_account_id,
                public_id=draft_public_id,
                target_debt_public_id=jpy_debt.public_id,
                expected_row_version=jpy_debt.row_version,
                idempotency_key=str(uuid4()),
            )
        assert excinfo.value.error == "currency_binding_drift"


def _candidate_confirm_call(db, home_env: str):
    """R15b-4 的最小确认创建调用（fabricated candidate match，不依赖 insights 聚合）。"""
    match = _RecurringCandidateMatch(
        merchant="咖啡店",
        merchant_key="coffee",
        frequency="monthly",
        amount_cents=1200,
        candidate={},
    )
    payload = RecurringCandidateConfirmRequest(
        merchant="咖啡店",
        amount_cents=1200,
        frequency="monthly",
    )
    return _create_recurring_item_from_candidate(
        db,
        tenant_id="owner",
        match=match,
        payload=payload,
        timezone_name=None,
    )


def test_recurring_candidate_confirm_gated_under_drift(monkeypatch) -> None:
    # R15b-4：候选确认创建 RecurringItem（门证据集的无绑定表）前过 ADR-0075 写门 ——
    # CNY 事实 + env=JPY → drift 拒，drift 窗口不得写入新无绑定行。
    _seed_cny_expense_fact_row()
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    get_settings.cache_clear()
    try:
        with SessionLocal() as db:
            with pytest.raises(AppError) as excinfo:
                _candidate_confirm_call(db, "JPY")
            assert excinfo.value.error == "currency_binding_configuration_drift"
    finally:
        monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
        get_settings.cache_clear()


def test_recurring_candidate_confirm_requires_versioned_writer_on_jpy(monkeypatch) -> None:
    # 非 CNY 新装不允许旧写者绕过 C03 版本合同。
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    get_settings.cache_clear()
    try:
        with SessionLocal() as db:
            with pytest.raises(AppError) as excinfo:
                _candidate_confirm_call(db, "JPY")
            assert excinfo.value.error == "client_upgrade_required"
            assert get_capability(db).state == "EMPTY"
    finally:
        monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
        get_settings.cache_clear()


def test_repeated_same_binding_resolution_is_idempotent(monkeypatch) -> None:
    # 同一持久化绑定重复解析成功；配置变更后立即拒绝。
    with SessionLocal() as db:
        resolve_write_capability(db)
        resolve_write_capability(db)
        monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
        get_settings.cache_clear()
        try:
            with pytest.raises(AppError) as excinfo:
                resolve_write_capability(db)
            assert excinfo.value.error == "currency_binding_configuration_drift"
        finally:
            monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
            get_settings.cache_clear()


def test_goal_create_passes_with_persisted_binding_matching_env() -> None:
    # 权威绑定已激活且与 env 一致时，目标写入正常完成。
    from app.schemas import GoalCreateRequest

    with SessionLocal() as db:
        resolve_write_capability(db)
        db.commit()
        response = create_goal(
            db,
            tenant_id="owner",
            payload=GoalCreateRequest(
                name="本月外卖",
                goal_type="spending_limit",
                period="monthly",
                month="2026-07",
                target_amount_cents=20000,
            ),
        )
        assert response.name == "本月外卖"
