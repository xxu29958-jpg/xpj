"""Write-time currency-binding drift gate (ADR-0061 C02 bridge, PR#255 R9).

env(``FX_HOME_CURRENCY_CODE``) 不是持久版本化绑定：已持久事实的
``home_currency_code`` 与当前 env 不一致时，任何以 env 盖章的新写入必须
fail closed（``currency_binding_drift`` 409）；空库首笔放行。读路径不走此门。
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.errors import AppError
from app.models import Expense, LedgerMember, MonthlyIncomePlan
from app.schemas import RepaymentCreateRequest
from app.services.currency_binding_service import assert_currency_binding_consistent
from app.services.debt_service._repayment import record_repayment
from app.services.exchange_rate_service import apply_currency_payload


def _idem_headers(app_headers: dict[str, str]) -> dict[str, str]:
    return {**app_headers, "Idempotency-Key": str(uuid4())}


def _create_cny_debt(client: TestClient, identity) -> None:
    response = client.post(
        "/api/debts",
        headers=_idem_headers(identity.app_headers),
        json={
            "direction": "i_owe",
            "counterparty_type": "external",
            "counterparty_label": "房东",
            "principal_amount_cents": 30000,
        },
    )
    assert response.status_code == 201, response.json()
    assert response.json()["home_currency_code"] == "CNY"


def test_debt_create_rejected_when_env_drifts_from_persisted_facts(
    client: TestClient, monkeypatch, *, identity
) -> None:
    # 漂移场景（bot 06:50 P1）：纯 CNY 事实安装把 env 改成 JPY → 首笔 JPY 欠款
    # 若放行即与 CNY 事实并存污染。写时门以写时事实为准：拒绝。
    _create_cny_debt(client, identity)

    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    get_settings.cache_clear()
    try:
        drifted = client.post(
            "/api/debts",
            headers=_idem_headers(identity.app_headers),
            json={
                "direction": "i_owe",
                "counterparty_type": "external",
                "counterparty_label": "同事",
                "principal_amount_cents": 1200,
            },
        )
        assert drifted.status_code == 409, drifted.json()
        assert drifted.json()["error"] == "currency_binding_drift"
    finally:
        monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
        get_settings.cache_clear()


def test_binding_gate_allows_first_record_on_empty_installation() -> None:
    # 空库（无任何持久事实）= 首笔 claim binding，放行。
    with SessionLocal() as db:
        assert_currency_binding_consistent(db, "JPY")


def test_binding_gate_allows_write_when_facts_share_binding(client: TestClient, *, identity) -> None:
    # 全一致（既有事实与 env 同币种）放行。
    _create_cny_debt(client, identity)
    with SessionLocal() as db:
        assert_currency_binding_consistent(db, "CNY")


def test_binding_gate_rejects_drift_via_expense_facts() -> None:
    # expense 臂：以 ORM 直接落一条 CNY 账单事实，门检查三表（debts/expenses/
    # repayment_proposals）任一不一致即拒。
    with SessionLocal() as db:
        db.add(Expense(tenant_id="owner", home_currency_code="CNY"))
        db.commit()
        with pytest.raises(AppError) as excinfo:
            assert_currency_binding_consistent(db, "JPY")
        assert excinfo.value.error == "currency_binding_drift"
        assert excinfo.value.status_code == 409


def test_misconfigured_env_still_fails_fast_before_gate(
    client: TestClient, monkeypatch, *, identity
) -> None:
    # env 本身配错（非支持集码）时写路径维持既有 fail-fast：currency_not_supported
    # 先于 drift 门抛出（门的 None/降级态只在读路径）。伪造码选 "ZZZ"：marker 审计
    # 词表（见 _audit_codebase.audit_todos）不含它。
    _create_cny_debt(client, identity)
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "ZZZ")
    get_settings.cache_clear()
    try:
        response = client.post(
            "/api/debts",
            headers=_idem_headers(identity.app_headers),
            json={
                "direction": "i_owe",
                "counterparty_type": "external",
                "counterparty_label": "同事",
                "principal_amount_cents": 1200,
            },
        )
        assert response.status_code == 422, response.json()
        assert response.json()["error"] == "currency_not_supported"
    finally:
        monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
        get_settings.cache_clear()


def _seed_cny_expense_fact() -> None:
    with SessionLocal() as db:
        db.add(Expense(tenant_id="owner", home_currency_code="CNY"))
        db.commit()


def test_metadata_only_payload_bypasses_gate_and_env_read(monkeypatch) -> None:
    # PR#255 R10②：纯元数据 PATCH（无金额/无 original 字段）不过门、连 env 都不读 ——
    # 配错的 env（"ZZZ"）下元数据维护不该 500。
    _seed_cny_expense_fact()
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "ZZZ")
    get_settings.cache_clear()
    try:
        with SessionLocal() as db:
            expense = Expense(tenant_id="owner", note="before")
            apply_currency_payload(
                db,
                tenant_id="owner",
                expense=expense,
                payload=SimpleNamespace(note="after"),
                amount_was_explicit=False,
            )
        assert expense.note == "before"  # 元数据路径不碰金额快照（note 由调用方自管）
    finally:
        monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
        get_settings.cache_clear()


def test_explicit_amount_payload_still_gated_under_drift(monkeypatch) -> None:
    # R10② 同伴钉：显式金额 PATCH 在盖章区过门 —— env 漂移（JPY vs CNY 事实）仍 409。
    _seed_cny_expense_fact()
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    get_settings.cache_clear()
    try:
        with SessionLocal() as db:
            expense = Expense(tenant_id="owner")
            with pytest.raises(AppError) as excinfo:
                apply_currency_payload(
                    db,
                    tenant_id="owner",
                    expense=expense,
                    payload=SimpleNamespace(amount_cents=1200),
                    amount_was_explicit=True,
                )
            assert excinfo.value.error == "currency_binding_drift"
    finally:
        monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
        get_settings.cache_clear()


def test_binding_prechecked_skips_per_row_gate(monkeypatch) -> None:
    # PR#255 R10①：批量写路径在批首已校验一次，行内经 binding_checked=True 跳过
    # per-row 门（避免每行 3 次全表 distinct）；门本身的环境由批首保证。
    _seed_cny_expense_fact()
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    get_settings.cache_clear()
    try:
        with SessionLocal() as db:
            expense = Expense(tenant_id="owner")
            apply_currency_payload(
                db,
                tenant_id="owner",
                expense=expense,
                payload=SimpleNamespace(amount_cents=1200),
                amount_was_explicit=True,
                binding_checked=True,
            )
        assert expense.amount_cents == 1200
        assert expense.home_currency_code == "JPY"
    finally:
        monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
        get_settings.cache_clear()


def test_repayment_draft_capture_rejected_on_non_cny_installation(
    client: TestClient, monkeypatch, *, identity
) -> None:
    # PR#255 R10③：Android 通知解析器按 CNY 分声明 amount_cents（无 FX 路径）——非 CNY
    # 安装把该整数按 home minor 盖章即 100× 错账，故后端整体拒建（跨币种捕获契约
    # 挂账 D9）。CNY 放行路径见 test_repayment_drafts.py 的 capture 钉。
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    get_settings.cache_clear()
    try:
        response = client.post(
            "/api/repayment-drafts",
            headers=identity.app_headers,
            json={"source": "alipay", "amount_cents": 120000},
        )
        assert response.status_code == 422, response.json()
        assert response.json()["error"] == "repayment_draft_currency_unsupported"
    finally:
        monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
        get_settings.cache_clear()


def _owner_account_id() -> int:
    with SessionLocal() as db:
        account_id = db.scalar(
            select(LedgerMember.account_id)
            .where(LedgerMember.ledger_id == "owner", LedgerMember.role == "owner")
            .limit(1)
        )
        assert account_id is not None
        return account_id


def _create_jpy_debt(client: TestClient, identity, monkeypatch) -> str:
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    get_settings.cache_clear()
    response = client.post(
        "/api/debts",
        headers=_idem_headers(identity.app_headers),
        json={
            "direction": "i_owe",
            "counterparty_type": "external",
            "counterparty_label": "房东",
            "principal_amount_cents": 50000,
        },
    )
    assert response.status_code == 201, response.json()
    assert response.json()["home_currency_code"] == "JPY"
    return response.json()["public_id"]


def test_repayment_draft_capture_rejected_when_env_drifts_back_to_cny(
    client: TestClient, monkeypatch, *, identity
) -> None:
    # R12-A：JPY 事实安装 env 漂回 CNY —— CNY 声明门放行但 drift 门必须拒（bot 09:28 P1）：
    # 否则 capture 后 confirm 会把 CNY 分整数按 JPY debt 入账。双门交集钉。
    _create_jpy_debt(client, identity, monkeypatch)
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "CNY")
    get_settings.cache_clear()
    try:
        response = client.post(
            "/api/repayment-drafts",
            headers=identity.app_headers,
            json={"source": "alipay", "amount_cents": 120000},
        )
        assert response.status_code == 409, response.json()
        assert response.json()["error"] == "currency_binding_drift"
    finally:
        monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
        get_settings.cache_clear()


def test_foreign_repayment_rejected_when_debt_currency_differs_from_env(
    client: TestClient, monkeypatch, *, identity
) -> None:
    # R12-C：外币还款换算按 env、折叠按 parent debt —— 两口径错位（JPY debt + env CNY）
    # 时按 drift 拒（错额/误报 overpay，bot 09:28 P1）。
    public_id = _create_jpy_debt(client, identity, monkeypatch)
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "CNY")
    get_settings.cache_clear()
    try:
        with SessionLocal() as db:
            with pytest.raises(AppError) as excinfo:
                record_repayment(
                    db,
                    tenant_id="owner",
                    public_id=public_id,
                    actor_account_id=_owner_account_id(),
                    payload=RepaymentCreateRequest(
                        amount_cents=None,
                        original_currency="USD",
                        original_amount=Decimal("100"),
                        expected_row_version=1,
                    ),
                    idempotency_key=str(uuid4()),
                )
            assert excinfo.value.error == "currency_binding_drift"
    finally:
        monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
        get_settings.cache_clear()


def test_foreign_repayment_allowed_when_debt_currency_matches_env(
    client: TestClient, monkeypatch, *, identity
) -> None:
    # R12-C 同伴钉：original 币种 == env == debt 冻结币种时，既有诚实换算不动（base 1:1）。
    public_id = _create_jpy_debt(client, identity, monkeypatch)
    try:
        with SessionLocal() as db:
            recorded = record_repayment(
                db,
                tenant_id="owner",
                public_id=public_id,
                actor_account_id=_owner_account_id(),
                payload=RepaymentCreateRequest(
                    amount_cents=None,
                    original_currency="JPY",
                    original_amount=Decimal("100"),
                    expected_row_version=1,
                ),
                idempotency_key=str(uuid4()),
            )
        # 门未拦（无 AppError 即放行）；折叠数学由 test_debt_repayment 族既有覆盖。
        assert recorded.repayment_public_id
    finally:
        monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
        get_settings.cache_clear()


def test_home_integer_repayment_allowed_under_drift(
    client: TestClient, monkeypatch, *, identity
) -> None:
    # R12-C 豁免钉：无 original 字段的整数透传按 parent debt 冻结币种解释（record 语义），
    # env 漂移不拦 —— 与 bot 评论区分的「豁免不动」面。
    public_id = _create_jpy_debt(client, identity, monkeypatch)
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "CNY")
    get_settings.cache_clear()
    try:
        with SessionLocal() as db:
            recorded = record_repayment(
                db,
                tenant_id="owner",
                public_id=public_id,
                actor_account_id=_owner_account_id(),
                payload=RepaymentCreateRequest(
                    amount_cents=100,
                    expected_row_version=1,
                ),
                idempotency_key=str(uuid4()),
            )
        assert recorded.repayment_public_id
    finally:
        monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
        get_settings.cache_clear()


def test_notification_draft_rejected_on_non_cny_with_partial_original_fields(
    client: TestClient, monkeypatch, *, identity
) -> None:
    # R12-E：仅币种无金额的残缺 FX 载荷 = 无 original 处理 —— 非 CNY 下拒（该路径不为
    # 部分 FX 设计）。成对完整放行见 R11 钉。
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    get_settings.cache_clear()
    try:
        response = client.post(
            "/api/expenses/notification-drafts",
            headers=identity.app_headers,
            json={"source": "wechat", "merchant": "星巴克", "original_currency": "JPY"},
        )
        assert response.status_code == 422, response.json()
        assert response.json()["error"] == "notification_draft_currency_unsupported"
    finally:
        monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
        get_settings.cache_clear()


def test_notification_draft_cny_with_partial_original_fields_matches_main_behavior(
    client: TestClient, *, identity
) -> None:
    # R12-E 回归钉：CNY 下门不触发，残缺 FX 载荷行为与 main 一致 —— 走外币分支按
    # fx pending 创建（挂起待汇率，而非本门的新错误码）。
    response = client.post(
        "/api/expenses/notification-drafts",
        headers=identity.app_headers,
        json={"source": "wechat", "merchant": "星巴克", "original_currency": "USD"},
    )
    assert response.status_code == 200, response.json()
    assert response.json()["original_currency_code"] == "USD"
    assert response.json()["fx_status"] == "pending"


def test_unbound_monetary_rows_block_non_cny_binding_claim(monkeypatch) -> None:
    # R12-F：仅有无币种列的遗留金额行（MonthlyIncomePlan，CNY 时代整数）+ env≠CNY →
    # 不得视为空库放行首笔绑定 → currency_binding_unresolved。
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
        with pytest.raises(AppError) as excinfo:
            assert_currency_binding_consistent(db, "JPY")
        assert excinfo.value.error == "currency_binding_unresolved"
        assert excinfo.value.status_code == 409
        # env==CNY 放行：存量无绑定行定义上即 CNY 分。
        assert_currency_binding_consistent(db, "CNY")


def test_unbound_rows_with_bound_fact_follow_drift_gate(client: TestClient, monkeypatch, *, identity) -> None:
    # R12-F：有绑定事实时仅按既有三表门裁决（不重复触发 unresolved）—— JPY debt +
    # income plan 行 + env=CNY → drift 门拒。
    _create_jpy_debt(client, identity, monkeypatch)
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
        with pytest.raises(AppError) as excinfo:
            assert_currency_binding_consistent(db, "CNY")
        assert excinfo.value.error == "currency_binding_drift"
    monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
    get_settings.cache_clear()
