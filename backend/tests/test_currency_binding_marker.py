"""PR#255 R13 绑定标记与 confirm 双闸的测试族（自 test_debt_binding_drift 拆出守 500 行门）。

覆盖：AppMeta 最小绑定标记（死锁复现/自愈/漂移）、三无绑定写服务接门、
RepaymentDraft 事实集（空库跨绑定首写拒）与 confirm 冻结币种比对。
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import SessionLocal
from app.errors import AppError
from app.models import AppMeta, Debt, Expense, MonthlyIncomePlan
from app.schemas import BudgetMonthlyUpdateRequest, GoalCreateRequest, RecurringCandidateConfirmRequest
from app.services.app_meta_service import get_value
from app.services.budget_service import upsert_monthly_budget
from app.services.currency_binding_service import (
    INSTALLATION_HOME_CURRENCY_KEY,
    _claim_binding_marker,
    assert_currency_binding_consistent,
)
from app.services.debt_service._repayment_draft_confirm import confirm_repayment_draft
from app.services.exchange_rate_service import apply_currency_payload
from app.services.goal_service import create_goal
from app.services.income_plan_service import create_income_plan
from app.services.recurring_candidate_confirmation_service import (
    _create_recurring_item_from_candidate,
    _RecurringCandidateMatch,
)
from app.services.time_service import now_utc
from tests.test_debt_binding_drift import (
    _create_cny_debt,
    _idem_headers,
    _owner_account_id,
)


def _seed_cny_expense_fact_row() -> None:
    with SessionLocal() as db:
        db.add(Expense(tenant_id="owner", home_currency_code="CNY"))
        db.commit()


def test_jpy_fresh_install_unbound_write_then_first_fact_claims_binding(monkeypatch) -> None:
    # R13-1 死锁复现场景：JPY 新装先写规划行（无绑定事实、无标记、无遗留行）→ 放行并
    # claim 标记=JPY；随后首笔绑定写（expense 口径）→ 标记==env 放行；绑定从此确立。
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    get_settings.cache_clear()
    try:
        with SessionLocal() as db:
            create_income_plan(
                db,
                tenant_id="owner",
                label="工资",
                source_type="salary",
                amount_cents=1200,
                pay_day=10,
            )
            marker = get_value(db, INSTALLATION_HOME_CURRENCY_KEY)
            assert marker == "JPY"
            expense = Expense(tenant_id="owner")
            apply_currency_payload(
                db,
                tenant_id="owner",
                expense=expense,
                payload=SimpleNamespace(amount_cents=1200),
                amount_was_explicit=True,
            )
            assert expense.home_currency_code == "JPY"
            assert_currency_binding_consistent(db, "JPY")
    finally:
        monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
        get_settings.cache_clear()


def test_legacy_unbound_rows_self_heal_marker_on_cny(monkeypatch) -> None:
    # R13-1：无标记 + 遗留无绑定行 + env==CNY → 放行并自愈补标=CNY（多币种未发布，
    # 存量无绑定行定义上即 CNY 分）。
    with SessionLocal() as db:
        db.add(
            MonthlyIncomePlan(
                tenant_id="owner",
                label="工资",
                source_type="salary",
                amount_cents=1_000_000,
                pay_day=10,
                status="active",
            )
        )
        db.commit()
        assert get_value(db, INSTALLATION_HOME_CURRENCY_KEY) is None
        assert_currency_binding_consistent(db, "CNY")
        assert get_value(db, INSTALLATION_HOME_CURRENCY_KEY) == "CNY"


def test_marker_disagreeing_with_env_rejects(monkeypatch) -> None:
    # R13-1：标记=JPY 而 env=CNY（配置漂移）→ drift 拒（标记优先于「空事实集=空库」）。
    with SessionLocal() as db:
        db.add(AppMeta(key=INSTALLATION_HOME_CURRENCY_KEY, value="JPY", updated_at=now_utc()))
        db.commit()
        with pytest.raises(AppError) as excinfo:
            assert_currency_binding_consistent(db, "CNY")
        assert excinfo.value.error == "currency_binding_drift"


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
            assert budget_exc.value.error == "currency_binding_drift"
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
            assert goal_exc.value.error == "currency_binding_drift"
            with pytest.raises(AppError) as income_exc:
                create_income_plan(
                    db,
                    tenant_id="owner",
                    label="工资",
                    source_type="salary",
                    amount_cents=1200,
                    pay_day=10,
                )
            assert income_exc.value.error == "currency_binding_drift"
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
        assert created.json()["error"] == "currency_binding_drift"
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
            assert excinfo.value.error == "currency_binding_drift"
    finally:
        monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
        get_settings.cache_clear()


def test_recurring_candidate_confirm_passes_on_jpy_fresh_install(monkeypatch) -> None:
    # R15b-4：JPY 新装（空库无标记）→ 门放行 + 同事务 claim 标记=JPY + 创建成功。
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    get_settings.cache_clear()
    try:
        with SessionLocal() as db:
            item = _candidate_confirm_call(db, "JPY")
            assert item.baseline_amount_cents == 1200
            assert get_value(db, INSTALLATION_HOME_CURRENCY_KEY) == "JPY"
    finally:
        monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
        get_settings.cache_clear()


def test_claim_marker_tolerates_concurrent_same_value_claim() -> None:
    # R15b-5：并发首写同 key PK 撞（同值）→ 第二次 claim 重读标记==env 视为成功；
    # 不同值 → drift（goal create 的 catch-all 不再把标记竞态误报为目标重名）。
    with SessionLocal() as db:
        _claim_binding_marker(db, "JPY")
        _claim_binding_marker(db, "JPY")  # 同值撞键容忍，不抛
        with pytest.raises(AppError) as excinfo:
            _claim_binding_marker(db, "CNY")
        assert excinfo.value.error == "currency_binding_drift"


def test_goal_create_passes_with_marker_already_matching_env() -> None:
    # R15b-5：标记已存在且==env（并发首写已盖章的场景）→ goal create 正常完成
    # （标记竞态不再经 catch-all 误报为「目标重名」409）。
    from app.schemas import GoalCreateRequest

    with SessionLocal() as db:
        db.add(AppMeta(key=INSTALLATION_HOME_CURRENCY_KEY, value="CNY", updated_at=now_utc()))
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




def test_csv_apply_all_invalid_batch_leaves_no_marker(monkeypatch, *, identity) -> None:
    # 遗留 U8：JPY 新装 + 全废批（行全部 validate-invalid，零可应用行）→ 不过门、
    # 不留无事实独存标记（旧时序：门挂 lease commit，批全废标记仍独存）。
    from io import BytesIO

    from app.services.csv_import_batch_service import apply_csv_import_batch, create_csv_import_batch

    del identity
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    get_settings.cache_clear()
    try:
        with SessionLocal() as db:
            batch = create_csv_import_batch(
                db,
                tenant_id="owner",
                file_name="all-invalid.csv",
                file_obj=BytesIO("amount_yuan,merchant,category,note\nabc,坏行,餐饮,x\n".encode()),
            )
            public_id = batch.public_id
        with SessionLocal() as db:
            apply_csv_import_batch(db, tenant_id="owner", public_id=public_id, batch_size=10)
        with SessionLocal() as db:
            assert get_value(db, INSTALLATION_HOME_CURRENCY_KEY) is None
    finally:
        monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
        get_settings.cache_clear()
