"""Write-time persisted currency-authority regression tests (ADR-0061 C02).

env(``FX_HOME_CURRENCY_CODE``) 只能初始化空库或校验持久化绑定；
配置漂移、旧非 CNY 写者和未取得 writer proof 的写入全部 fail closed。
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from inspect import signature
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError

from app.config import get_settings
from app.database import SessionLocal
from app.errors import AppError
from app.models import Debt, Expense, InstallationCurrencyBinding, LedgerMember, MonthlyIncomePlan, Repayment
from app.runtime_compatibility_contract import (
    RUNTIME_COMPATIBILITY_SESSION_KEY,
    RuntimeCompatibilityRequest,
)
from app.schemas import RepaymentCreateRequest
from app.services.currency_binding_service import (
    assert_currency_binding_consistent,
    get_capability,
)
from app.services.debt_service._repayment import record_repayment
from app.services.exchange_rate_service import apply_currency_payload, upsert_exchange_rate
from app.services.time_service import now_utc
from tests._infra.currency import activate_test_currency_authority

pytestmark = pytest.mark.currency_binding_unbound


def _mark_legacy_http_writer(db) -> None:
    db.info[RUNTIME_COMPATIBILITY_SESSION_KEY] = RuntimeCompatibilityRequest(
        api_version=None,
        currency_binding=None,
    )


def _idem_headers(app_headers: dict[str, str]) -> dict[str, str]:
    return {**app_headers, "Idempotency-Key": str(uuid4())}


def _create_cny_debt(client: TestClient, identity) -> None:
    with SessionLocal() as db:
        activate_test_currency_authority(db, "CNY")
        db.commit()
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


def _seed_active_jpy_debt() -> str:
    """Build an ACTIVE JPY fixture without pretending a legacy writer is C03-capable."""
    with SessionLocal() as db:
        binding = db.get(InstallationCurrencyBinding, 1)
        assert binding is not None
        activated_at = now_utc()
        binding.state = "ACTIVE"
        binding.home_currency_code = "JPY"
        binding.minor_unit_exponent = 0
        binding.rounding_mode = "ROUND_HALF_UP"
        binding.binding_revision = 1
        binding.provenance = "TEST_FIXTURE"
        binding.evidence_sha256 = "0" * 64
        binding.updated_at = activated_at
        binding.activated_at = activated_at
        db.flush()
        db.execute(text("SELECT set_config('xpj.currency_writer', '1:1', true)"))
        owner_account_id = _owner_account_id()
        debt = Debt(
            tenant_id="owner",
            owner_account_id=owner_account_id,
            created_by_account_id=owner_account_id,
            direction="i_owe",
            counterparty_type="external",
            principal_amount_cents=50000,
            home_currency_code="JPY",
            status="open",
            source_type="manual",
        )
        db.add(debt)
        db.commit()
        public_id = debt.public_id
        db.execute(text("SELECT set_config('xpj.currency_writer', '', true)"))
        db.commit()
        return public_id


def test_debt_create_keeps_confirmed_currency_when_environment_changes(client: TestClient, monkeypatch, *, identity) -> None:
    _create_cny_debt(client, identity)
    for configured in ("JPY", "ZZZ"):
        monkeypatch.setenv("FX_HOME_CURRENCY_CODE", configured)
        response = client.post("/api/debts", headers=_idem_headers(identity.app_headers), json={
            "direction": "i_owe", "counterparty_type": "external",
            "counterparty_label": "同事", "principal_amount_cents": 1200,
        })
        assert response.status_code == 201, response.json()
        assert response.json()["home_currency_code"] == "CNY"
        assert response.json()["principal_amount_cents"] == 1200


def test_non_cny_confirmed_currency_requires_versioned_writer() -> None:
    with SessionLocal() as db:
        activate_test_currency_authority(db, "JPY")
        _mark_legacy_http_writer(db)
        with pytest.raises(AppError) as refused:
            assert_currency_binding_consistent(db, "JPY")
        assert refused.value.error == "client_upgrade_required"
        assert get_capability(db).home_currency_code == "JPY"


def test_binding_gate_allows_write_when_facts_share_binding(client: TestClient, *, identity) -> None:
    # 全一致（既有事实与 env 同币种）放行。
    _create_cny_debt(client, identity)
    with SessionLocal() as db:
        assert_currency_binding_consistent(db, "CNY")


def test_binding_gate_rejects_drift_via_expense_facts() -> None:
    # expense 臂：以 ORM 直接落一条 CNY 账单事实，门检查三表（debts/expenses/
    # repayment_proposals）任一不一致即拒。
    with SessionLocal() as db:
        activate_test_currency_authority(db, "CNY")
        db.add(Expense(tenant_id="owner", home_currency_code="CNY"))
        db.commit()
        with pytest.raises(AppError) as excinfo:
            assert_currency_binding_consistent(db, "JPY")
        assert excinfo.value.error == "currency_binding_revision_conflict"
        assert excinfo.value.status_code == 409




def _seed_cny_expense_fact() -> None:
    with SessionLocal() as db:
        activate_test_currency_authority(db, "CNY")
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


def test_explicit_amount_payload_uses_confirmed_basis_despite_environment(monkeypatch) -> None:
    _seed_cny_expense_fact()
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    with SessionLocal() as db:
        expense = Expense(tenant_id="owner")
        apply_currency_payload(db, tenant_id="owner", expense=expense,
            payload=SimpleNamespace(amount_cents=1200), amount_was_explicit=True)
        assert expense.amount_cents == 1200
        assert expense.original_amount_minor == 1200
        assert expense.home_currency_code == "CNY"


def test_currency_payload_has_no_binding_bypass_parameter() -> None:
    assert "binding_checked" not in signature(apply_currency_payload).parameters


def test_repayment_draft_capture_rejected_on_non_cny_installation(client: TestClient, monkeypatch, *, identity) -> None:
    # PR#255 R10③：Android 通知解析器按 CNY 分声明 amount_cents（无 FX 路径）——非 CNY
    # 安装把该整数按 home minor 盖章即 100× 错账，故后端整体拒建（跨币种捕获契约
    # 挂账 D9）。CNY 放行路径见 test_repayment_drafts.py 的 capture 钉。
    with SessionLocal() as db:
        activate_test_currency_authority(db, "JPY")
        db.commit()
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
    _ = (client, identity)
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    get_settings.cache_clear()
    return _seed_active_jpy_debt()


def test_legacy_cny_repayment_capture_cannot_reinterpret_a_jpy_binding(
    client: TestClient, monkeypatch, *, identity
) -> None:
    # 旧捕获载荷只声明人民币分。环境变量不能把它伪装为 JPY 最小单位。
    _create_jpy_debt(client, identity, monkeypatch)
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "CNY")
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


def test_foreign_repayment_uses_confirmed_debt_basis_despite_environment(client: TestClient, monkeypatch, *, identity) -> None:
    public_id = _create_jpy_debt(client, identity, monkeypatch)
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "CNY")
    paid_at = datetime(2026, 9, 8, 2, tzinfo=UTC)
    with SessionLocal() as db:
        upsert_exchange_rate(db, tenant_id="owner", currency_code="USD", home_currency_code="JPY", rate_date=paid_at.date(), rate_to_cny=Decimal("150"))
        record_repayment(db, tenant_id="owner", public_id=public_id, actor_account_id=_owner_account_id(),
            payload=RepaymentCreateRequest(original_currency="USD", original_amount=Decimal("1"), paid_at=paid_at, expected_row_version=1),
            idempotency_key=str(uuid4()))
        repayment = db.scalar(select(Repayment))
        assert repayment.amount_cents == 150
        assert repayment.original_currency_code == "USD"
        assert repayment.original_amount_minor == 100
        assert db.scalar(select(Debt).where(Debt.public_id == public_id)).home_currency_code == "JPY"


def test_foreign_repayment_requires_versioned_writer_when_debt_currency_matches_env(
    client: TestClient, monkeypatch, *, identity
) -> None:
    # R12-C 同伴钉：original 币种 == env == debt 冻结币种时，既有诚实换算不动（base 1:1）。
    public_id = _create_jpy_debt(client, identity, monkeypatch)
    try:
        with SessionLocal() as db, pytest.raises(AppError) as excinfo:
            _mark_legacy_http_writer(db)
            record_repayment(
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
        assert excinfo.value.error == "client_upgrade_required"
    finally:
        monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
        get_settings.cache_clear()


def test_home_integer_repayment_uses_confirmed_basis_despite_environment(client: TestClient, monkeypatch, *, identity) -> None:
    public_id = _create_jpy_debt(client, identity, monkeypatch)
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "CNY")
    with SessionLocal() as db:
        record_repayment(db, tenant_id="owner", public_id=public_id, actor_account_id=_owner_account_id(),
            payload=RepaymentCreateRequest(amount_cents=100, expected_row_version=1), idempotency_key=str(uuid4()))
        assert db.scalar(select(Repayment.amount_cents)) == 100


def test_notification_draft_rejected_on_non_cny_with_partial_original_fields(
    client: TestClient, monkeypatch, *, identity
) -> None:
    # R12-E：仅币种无金额的残缺 FX 载荷 = 无 original 处理 —— 非 CNY 下拒（该路径不为
    # 部分 FX 设计）。成对完整放行见 R11 钉。
    with SessionLocal() as db:
        activate_test_currency_authority(db, "JPY")
        db.commit()
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
    with SessionLocal() as db:
        activate_test_currency_authority(db, "CNY")
        db.commit()
    response = client.post(
        "/api/expenses/notification-drafts",
        headers=identity.app_headers,
        json={"source": "wechat", "merchant": "星巴克", "original_currency": "USD"},
    )
    assert response.status_code == 200, response.json()
    assert response.json()["original_currency_code"] == "USD"
    assert response.json()["fx_status"] == "pending"


def test_empty_binding_database_fence_rejects_raw_monetary_write() -> None:
    # 历史无币种金额行只能在 migration 时被识别为 ADOPTION_REQUIRED；
    # 运行期原始 ORM 写不得重建该模糊状态。
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
        with pytest.raises(ProgrammingError, match="XPJ_CURRENCY_FENCE"):
            db.commit()
        db.rollback()
        assert get_capability(db).state == "EMPTY"


def test_active_jpy_binding_rejects_legacy_unversioned_writer(client: TestClient, monkeypatch, *, identity) -> None:
    # ACTIVE JPY 已是明确事实，但 C02 时期旧写者仍不得伪造 C03 版本证据。
    _create_jpy_debt(client, identity, monkeypatch)
    with SessionLocal() as db:
        _mark_legacy_http_writer(db)
        with pytest.raises(AppError) as excinfo:
            from app.services.income_plan_service import create_income_plan

            create_income_plan(
                db,
                tenant_id="owner",
                label="工资",
                source_type="salary",
                amount_cents=1_000_000,
                pay_day=10,
            )
        assert excinfo.value.error == "client_upgrade_required"
    monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
    get_settings.cache_clear()


def _seed_cny_expense_fact_row() -> None:
    with SessionLocal() as db:
        activate_test_currency_authority(db, "CNY")
        db.add(Expense(tenant_id="owner", home_currency_code="CNY"))
        db.commit()
