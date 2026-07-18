"""Currency-minor-unit contracts for Web Debt fact forms."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings


def _headers(identity) -> dict[str, str]:
    return {**identity.app_headers, "Idempotency-Key": str(uuid4())}


def _create_debt(
    web_client: TestClient,
    *,
    identity,
    principal_amount_cents: int,
) -> dict:
    response = web_client.post(
        "/api/debts",
        headers=_headers(identity),
        json={
            "direction": "i_owe",
            "counterparty_type": "external",
            "counterparty_label": "整数币种测试",
            "principal_amount_cents": principal_amount_cents,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _form(
    debt: dict,
    *,
    idempotency_key: str,
    **values: str,
) -> dict[str, str]:
    return {
        "csrf_token": "test-client-bypasses-middleware-check",
        "ledger_id": "owner",
        "expected_row_version": str(debt["row_version"]),
        "idempotency_key": idempotency_key,
        **values,
    }


def _detail(web_client: TestClient, *, identity, public_id: str) -> dict:
    response = web_client.get(
        f"/api/debts/{public_id}",
        headers=identity.app_headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _assert_zero_fraction_form(
    page_text: str,
    *,
    currency_code: str,
    currency_symbol: str,
) -> None:
    assert 'name="amount_major"' in page_text
    assert f"本次还款（{currency_code} · {currency_symbol}，仅支持整数）" in page_text
    assert 'min="1"' in page_text
    assert 'step="1"' in page_text
    assert 'inputmode="numeric"' in page_text


def _exercise_zero_fraction_actions(
    web_client: TestClient,
    *,
    identity,
    debt: dict,
    currency_code: str,
) -> None:
    repayment = web_client.post(
        f"/web/debts/{debt['public_id']}/repayments",
        data=_form(
            debt,
            idempotency_key=str(uuid4()),
            amount_major="100",
        ),
    )
    assert repayment.status_code == 200
    assert "还款事实已记录" in repayment.text
    current = _detail(
        web_client,
        identity=identity,
        public_id=debt["public_id"],
    )
    assert current["paid_amount_cents"] == 100
    assert current["remaining_amount_cents"] == 9_900

    adjustment = web_client.post(
        f"/web/debts/{debt['public_id']}/adjustments",
        data=_form(
            current,
            idempotency_key=str(uuid4()),
            amount_major="-50",
            reason="整数币种修正",
        ),
    )
    assert adjustment.status_code == 200
    assert "本金调整事实已记录" in adjustment.text
    adjusted = _detail(
        web_client,
        identity=identity,
        public_id=debt["public_id"],
    )
    assert adjusted["principal_amount_cents"] == 10_000
    assert adjusted["remaining_amount_cents"] == 9_850

    decimal_rejected = web_client.post(
        f"/web/debts/{debt['public_id']}/repayments",
        data=_form(
            adjusted,
            idempotency_key=str(uuid4()),
            amount_major="1.5",
        ),
    )
    assert decimal_rejected.status_code == 200
    assert f"{currency_code} 金额只能填写整数" in decimal_rejected.text
    unchanged = _detail(
        web_client,
        identity=identity,
        public_id=debt["public_id"],
    )
    assert unchanged["remaining_amount_cents"] == 9_850
    assert unchanged["row_version"] == adjusted["row_version"]


@pytest.mark.parametrize(
    ("currency_code", "currency_symbol"),
    [
        pytest.param("JPY", "¥", id="jpy"),
        pytest.param("KRW", "₩", id="krw"),
    ],
)
def test_web_zero_fraction_debt_actions_use_frozen_currency_minor_units(
    web_client: TestClient,
    monkeypatch,
    identity,
    currency_code: str,
    currency_symbol: str,
) -> None:
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", currency_code)
    get_settings.cache_clear()
    try:
        debt = _create_debt(
            web_client,
            identity=identity,
            principal_amount_cents=10_000,
        )
        assert debt["home_currency_code"] == currency_code
        page = web_client.get(
            f"/web/debts/{debt['public_id']}?ledger_id=owner",
        )
        assert page.status_code == 200
        _assert_zero_fraction_form(
            page.text,
            currency_code=currency_code,
            currency_symbol=currency_symbol,
        )

        # The Debt keeps its creation-time currency even if server configuration
        # changes before a later fact is written.
        monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "CNY")
        get_settings.cache_clear()
        _exercise_zero_fraction_actions(
            web_client,
            identity=identity,
            debt=debt,
            currency_code=currency_code,
        )
    finally:
        get_settings.cache_clear()
