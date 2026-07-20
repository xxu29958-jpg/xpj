"""Currency-minor-unit contracts for Web/Owner major-unit projections.

The database columns still use their historical ``*_cents`` names. These
tests prove that form/display boundaries derive the scale from the
authoritative currency code instead of assuming every stored unit is 1/100.
(Template-structure assertions of the #218 web workbench are deferred to the
218-D slice; this file pins the minor-unit semantics that exist on main.)
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.errors import AppError
from app.fx_constants import (
    CURRENCY_MINOR_UNIT_DIGITS,
    DEFAULT_SUPPORTED_CURRENCY_CODES,
)
from app.models import Budget
from app.routes.web_common import _expense_amount_labels
from app.services.currency_common import (
    average_minor_amount,
    home_currency_code,
    minor_amount_label,
    minor_unit_digits,
    normalize_currency_code,
    supported_currency_codes,
)


def test_product_currency_minor_metadata_is_explicit_and_closed() -> None:
    assert set(CURRENCY_MINOR_UNIT_DIGITS) == set(DEFAULT_SUPPORTED_CURRENCY_CODES)
    assert {code: minor_unit_digits(code) for code in DEFAULT_SUPPORTED_CURRENCY_CODES} == CURRENCY_MINOR_UNIT_DIGITS


@pytest.mark.parametrize("currency_code", ["KWD", "人民币", "US1"])
def test_unknown_or_non_ascii_currency_code_fails_closed(
    currency_code: str,
) -> None:
    with pytest.raises(AppError) as exc_info:
        normalize_currency_code(currency_code)
    assert exc_info.value.error == "currency_not_supported"


@pytest.mark.parametrize(
    ("env_name", "env_value", "resolver"),
    [
        pytest.param(
            "FX_HOME_CURRENCY_CODE",
            "KWD",
            home_currency_code,
            id="unknown-home",
        ),
        pytest.param(
            "FX_SUPPORTED_CURRENCY_CODES",
            "CNY,KWD",
            supported_currency_codes,
            id="unknown-supported-code",
        ),
        pytest.param(
            "FX_SUPPORTED_CURRENCY_CODES",
            "CNY,人民币",
            supported_currency_codes,
            id="non-ascii-supported-code",
        ),
    ],
)
def test_invalid_currency_configuration_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    env_name: str,
    env_value: str,
    resolver,
) -> None:
    monkeypatch.setenv(env_name, env_value)
    get_settings.cache_clear()
    try:
        with pytest.raises(AppError) as exc_info:
            resolver()
        assert exc_info.value.error == "currency_not_supported"
    finally:
        get_settings.cache_clear()


def test_money_label_places_negative_sign_before_currency_symbol() -> None:
    assert minor_amount_label(-1234, "CNY") == "-¥12.34"


def test_foreign_expense_metadata_always_names_original_currency() -> None:
    primary, pending_meta = _expense_amount_labels(
        SimpleNamespace(
            home_currency_code="CNY",
            original_currency_code="JPY",
            original_amount_minor=1234,
            amount_cents=None,
            fx_status="pending",
            exchange_rate_date=None,
            exchange_rate_to_cny=None,
        )
    )
    assert primary == "¥1,234"
    assert pending_meta and "汇率待同步" in pending_meta

    _, ready_meta = _expense_amount_labels(
        SimpleNamespace(
            home_currency_code="CNY",
            original_currency_code="JPY",
            original_amount_minor=1234,
            amount_cents=6000,
            fx_status="ready",
            exchange_rate_date=None,
            exchange_rate_to_cny="0.0486",
        )
    )
    assert ready_meta and "≈ ¥60.00" in ready_meta


@pytest.mark.parametrize(
    ("currency_code", "major_input", "invalid_input", "expected_minor"),
    [
        pytest.param("CNY", "12.34", "12.345", 1234, id="cny-two-fraction"),
        pytest.param("JPY", "1234", "1.5", 1234, id="jpy-zero-fraction"),
        pytest.param("KRW", "1234", "1.5", 1234, id="krw-zero-fraction"),
    ],
)
def test_web_budget_write_and_reject_follow_home_currency_minor_units(
    web_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    currency_code: str,
    major_input: str,
    invalid_input: str,
    expected_minor: int,
) -> None:
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", currency_code)
    get_settings.cache_clear()
    try:
        saved = web_client.post(
            "/web/budgets/save",
            data={
                "ledger_id": "owner",
                "month": "2026-05",
                "total_amount_yuan": major_input,
            },
            follow_redirects=False,
        )
        assert saved.status_code == 303, saved.text
        with SessionLocal() as db:
            stored = db.scalar(
                select(Budget.total_amount_cents).where(Budget.tenant_id == "owner").where(Budget.month == "2026-05")
            )
        assert stored == expected_minor

        rejected = web_client.post(
            "/web/budgets/save",
            data={
                "ledger_id": "owner",
                "month": "2026-05",
                "total_amount_yuan": invalid_input,
            },
        )
        assert rejected.status_code == 200
        with SessionLocal() as db:
            unchanged = db.scalar(
                select(Budget.total_amount_cents).where(Budget.tenant_id == "owner").where(Budget.month == "2026-05")
            )
        assert unchanged == expected_minor
    finally:
        get_settings.cache_clear()


def test_reports_average_rounds_integer_minor_units_half_up() -> None:
    assert average_minor_amount(101, 2) == 51
    assert average_minor_amount(100, 3) == 33
    assert average_minor_amount(0, 0) == 0
