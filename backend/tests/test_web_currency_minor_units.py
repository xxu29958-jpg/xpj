"""Currency-minor-unit contracts for Web/Owner major-unit projections.

The database columns still use their historical ``*_cents`` names. These
tests prove that Web form/display boundaries derive the scale from the
authoritative currency code instead of assuming every stored unit is 1/100.
"""

from __future__ import annotations

from datetime import UTC, datetime
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
from app.models import (
    Budget,
    Expense,
)
from app.routes.web_common import _expense_amount_labels
from app.routes.web_import_export import _import_row_view
from app.routes.web_reports import _six_month_average_minor
from app.services import web_stats_service
from app.services.currency_common import (
    home_currency_code,
    minor_amount_label,
    minor_unit_digits,
    normalize_currency_code,
    supported_currency_codes,
)
from app.services.owner_console_service import _index as owner_index
from app.services.owner_console_service._recycle_bin import _money
from app.services.reports_service import six_month_summary
from app.services.time_service import now_utc


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
    assert minor_amount_label(-1234, "JPY") == "-¥1,234"


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
    assert pending_meta == "JPY · 汇率待同步"

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
    assert ready_meta and ready_meta.startswith("JPY · ≈ ¥60.00")


@pytest.mark.parametrize(
    (
        "currency_code",
        "major_input",
        "invalid_input",
        "expected_minor",
        "expected_value",
        "symbol",
        "step",
        "inputmode",
    ),
    [
        pytest.param(
            "CNY",
            "12.34",
            "12.345",
            1234,
            "12.34",
            "¥",
            "0.01",
            "decimal",
            id="cny-two-fraction",
        ),
        pytest.param(
            "JPY",
            "1234",
            "1.5",
            1234,
            "1234",
            "¥",
            "1",
            "numeric",
            id="jpy-zero-fraction",
        ),
        pytest.param(
            "KRW",
            "1234",
            "1.5",
            1234,
            "1234",
            "₩",
            "1",
            "numeric",
            id="krw-zero-fraction",
        ),
    ],
)
def test_web_budget_display_and_write_follow_home_currency_minor_units(
    web_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    currency_code: str,
    major_input: str,
    invalid_input: str,
    expected_minor: int,
    expected_value: str,
    symbol: str,
    step: str,
    inputmode: str,
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

        page = web_client.get("/web/budgets?ledger_id=owner&month=2026-05")
        assert page.status_code == 200
        assert page.context["budget"]["total_yuan"] == expected_value
        input_meta = page.context["home_currency_input"]
        assert input_meta["currency_code"] == currency_code
        assert input_meta["currency_symbol"] == symbol
        assert input_meta["amount_step"] == step
        assert input_meta["inputmode"] == inputmode
        assert f'data-home-currency="{currency_code}"' in page.text
        assert f'data-home-currency-minor-digits="{0 if step == "1" else 2}"' in page.text

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


@pytest.mark.parametrize(
    ("currency_code", "symbol"),
    [
        pytest.param("JPY", "¥", id="owner-jpy"),
        pytest.param("KRW", "₩", id="owner-krw"),
    ],
)
def test_owner_index_and_recycle_bin_use_configured_currency_projection(
    monkeypatch: pytest.MonkeyPatch,
    *,
    currency_code: str,
    symbol: str,
) -> None:
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", currency_code)
    get_settings.cache_clear()
    monkeypatch.setattr(
        owner_index,
        "get_monthly_budget",
        lambda *_args, **_kwargs: SimpleNamespace(
            configured=True,
            total_amount_cents=1234,
            rollover_amount_cents=0,
            spent_amount_cents=234,
            remaining_amount_cents=1000,
            overspent_amount_cents=0,
            category_budgets=[],
        ),
    )
    try:
        status = owner_index._budget_status_for_primary_ledger(
            SimpleNamespace(),
            SimpleNamespace(ledger_id="owner", name="我的小票夹"),
        )
        assert status is not None
        assert status.total_amount_yuan == "1234"
        assert status.spent_amount_yuan == "234"
        assert _money(1234) == f"{symbol}1,234"
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("currency_code", ["JPY", "KRW"])
def test_reports_and_web_stats_numeric_projections_use_home_currency_minor_units(
    identity,
    monkeypatch: pytest.MonkeyPatch,
    *,
    currency_code: str,
) -> None:
    del identity
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", currency_code)
    get_settings.cache_clear()
    now = now_utc()
    with SessionLocal() as db:
        db.add(
            Expense(
                tenant_id="owner",
                amount_cents=1234,
                home_currency_code=currency_code,
                original_currency_code=currency_code,
                original_amount_minor=1234,
                merchant="零小数统计",
                category="其他",
                source="手动记账",
                status="confirmed",
                expense_time=datetime(2026, 5, 4, 1, 0, tzinfo=UTC),
                confirmed_at=now,
            )
        )
        db.commit()

    try:
        with SessionLocal() as db:
            days = web_stats_service.confirmed_by_day(db, "owner", "2026-05")
            six_month = six_month_summary(
                db,
                anchor_month="2026-05",
                tenant_id="owner",
                timezone_name="Asia/Shanghai",
            )
        assert days == [
            {
                "date": "2026-05-04",
                "amount_cents": 1234,
                "amount_yuan": 1234,
                "count": 1,
            }
        ]
        may = next(row for row in six_month if row["month"] == "2026-05")
        assert may["amount_cents"] == 1234
        assert may["amount_major"] == 1234
        assert may["amount_value"] == "1234"
        assert may["amount_yuan"] == 1234
    finally:
        get_settings.cache_clear()


def test_reports_average_rounds_integer_minor_units_half_up() -> None:
    assert _six_month_average_minor([{"amount_cents": 1}, {"amount_cents": 2}]) == 2
    assert _six_month_average_minor([{"amount_cents": 2}, {"amount_cents": 3}]) == 3
    assert _six_month_average_minor([]) == 0


def test_import_batch_preview_formats_the_frozen_original_currency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "KRW")
    get_settings.cache_clear()
    try:
        legacy_cny = SimpleNamespace(
            amount_cents=1234,
            original_currency_code="CNY",
            original_amount_minor=1234,
            model_dump=lambda: {"line_number": 2},
        )
        frozen_jpy = SimpleNamespace(
            amount_cents=None,
            original_currency_code="JPY",
            original_amount_minor=1200,
            model_dump=lambda: {"line_number": 3},
        )
        legacy_view = _import_row_view(legacy_cny)
        frozen_view = _import_row_view(frozen_jpy)
        assert legacy_view["amount_label"] == "¥12.34"
        assert legacy_view["amount_currency_code"] == "CNY"
        assert legacy_view["amount_is_foreign"] is True
        assert frozen_view["amount_label"] == "¥1,200"
        assert frozen_view["amount_value"] == "1200"
    finally:
        get_settings.cache_clear()


def test_web_search_formats_expense_with_its_frozen_currency(
    web_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "CNY")
    get_settings.cache_clear()
    now = now_utc()
    with SessionLocal() as db:
        db.add(
            Expense(
                tenant_id="owner",
                amount_cents=1234,
                home_currency_code="JPY",
                original_currency_code="JPY",
                original_amount_minor=1234,
                merchant="Frozen JPY Search",
                category="其他",
                source="手动记账",
                status="pending",
                expense_time=now,
            )
        )
        db.commit()
    try:
        response = web_client.get("/web/search?ledger_id=owner&q=Frozen%20JPY%20Search")
        assert response.status_code == 200
        assert "Frozen JPY Search" in response.text
        assert "¥1,234" in response.text
        assert "¥12.34" not in response.text
    finally:
        get_settings.cache_clear()
