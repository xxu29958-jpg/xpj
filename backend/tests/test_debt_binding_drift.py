"""Write-time currency-binding drift gate (ADR-0061 C02 bridge, PR#255 R9).

env(``FX_HOME_CURRENCY_CODE``) 不是持久版本化绑定：已持久事实的
``home_currency_code`` 与当前 env 不一致时，任何以 env 盖章的新写入必须
fail closed（``currency_binding_drift`` 409）；空库首笔放行。读路径不走此门。
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import SessionLocal
from app.errors import AppError
from app.models import Expense
from app.services.currency_binding_service import assert_currency_binding_consistent


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
