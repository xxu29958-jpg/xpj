"""Currency-minor-unit contracts for Web Debt fact forms."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import Debt, LedgerMember
from app.services.time_service import now_utc
from tests._infra.currency import activate_test_currency_authority


def _seed_adopted_debt(
    *,
    currency_code: str,
    principal_amount_cents: int,
) -> str:
    with SessionLocal() as db:
        activate_test_currency_authority(db, currency_code)
        account_id = db.scalar(
            select(LedgerMember.account_id)
            .where(LedgerMember.ledger_id == "owner", LedgerMember.role == "owner")
            .limit(1)
        )
        assert account_id is not None
        timestamp = now_utc()
        debt = Debt(
            tenant_id="owner",
            owner_account_id=account_id,
            created_by_account_id=account_id,
            direction="i_owe",
            counterparty_type="external",
            counterparty_label="整数币种测试",
            principal_amount_cents=principal_amount_cents,
            home_currency_code=currency_code,
            status="open",
            source_type="manual",
            created_at=timestamp,
            updated_at=timestamp,
        )
        db.add(debt)
        db.commit()
        return debt.public_id


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
    assert "当前客户端版本过旧，无法安全完成此操作，请先升级。" in repayment.text
    current = _detail(
        web_client,
        identity=identity,
        public_id=debt["public_id"],
    )
    assert current["paid_amount_cents"] == 0
    assert current["remaining_amount_cents"] == 10_000
    assert current["row_version"] == debt["row_version"]

    decimal_rejected = web_client.post(
        f"/web/debts/{debt['public_id']}/repayments",
        data=_form(
            current,
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
    assert unchanged["remaining_amount_cents"] == 10_000
    assert unchanged["row_version"] == current["row_version"]


@pytest.mark.parametrize(
    ("currency_code", "currency_symbol"),
    [
        pytest.param("JPY", "¥", id="jpy"),
        pytest.param("KRW", "₩", id="krw"),
    ],
)
@pytest.mark.currency_binding_unbound
def test_web_zero_fraction_debt_forms_keep_frozen_units_and_require_versioned_writer(
    web_client: TestClient,
    monkeypatch,
    identity,
    currency_code: str,
    currency_symbol: str,
) -> None:
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", currency_code)
    get_settings.cache_clear()
    try:
        public_id = _seed_adopted_debt(
            currency_code=currency_code,
            principal_amount_cents=10_000,
        )
        debt = _detail(
            web_client,
            identity=identity,
            public_id=public_id,
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
        assert 'placeholder="如 -1200"' in page.text
        assert 'placeholder="如 -10.00"' not in page.text

        # C02 can render frozen facts but rejects legacy writes; C03 supplies
        # the versioned client tuple that makes this path writable again.
        _exercise_zero_fraction_actions(
            web_client,
            identity=identity,
            debt=debt,
            currency_code=currency_code,
        )
    finally:
        get_settings.cache_clear()
