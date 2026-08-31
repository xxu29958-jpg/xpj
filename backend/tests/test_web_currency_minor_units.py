"""Currency-minor-unit contracts for Web/Owner major-unit projections.

The database columns still use their historical ``*_cents`` names. These
tests prove that form/display boundaries derive the scale from the
authoritative currency code instead of assuming every stored unit is 1/100.
(Template-structure assertions of the #218 web workbench are deferred to the
218-D slice; this file pins the minor-unit semantics that exist on main.)
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from _web_overview_test_support import seed_confirmed_expense_fact
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
from app.routes.web_common import (
    _expense_amount_labels,
    _minor_amount_label,
    _minor_amount_value,
)
from app.services.currency_common import (
    average_minor_amount,
    home_currency_code,
    minor_amount_label,
    minor_unit_digits,
    normalize_currency_code,
    supported_currency_codes,
)
from app.services.owner_console_service._common import (
    _amount_yuan as _owner_amount_yuan,
)
from app.services.time_service import current_month


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
        if currency_code == "CNY":
            assert saved.status_code == 303, saved.text
        else:
            assert saved.status_code == 200, saved.text
            assert "服务端币种配置与已持久化的本位币绑定不一致" in saved.text
        with SessionLocal() as db:
            stored = db.scalar(
                select(Budget.total_amount_cents).where(Budget.tenant_id == "owner").where(Budget.month == "2026-05")
            )
        assert stored == (expected_minor if currency_code == "CNY" else None)

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
        assert unchanged == (expected_minor if currency_code == "CNY" else None)
    finally:
        get_settings.cache_clear()


def test_reports_average_rounds_integer_minor_units_half_up() -> None:
    assert average_minor_amount(101, 2) == 51
    assert average_minor_amount(100, 3) == 33
    assert average_minor_amount(0, 0) == 0


def test_web_common_minor_label_delegates_to_currency_common_divmod() -> None:
    """C5b-3: /web 的 ``_minor_amount_label`` / ``_minor_amount_value`` 委托
    currency_common 的 divmod 族，不再自实现 ``/100`` float —— 零小数币种、
    两位小数币种、负数符号位与 None 语义与 currency_common 完全一致。"""
    assert _minor_amount_label(5000, "JPY") == "¥5,000"
    assert _minor_amount_label(123400, "CNY") == "¥1,234.00"
    assert _minor_amount_label(-1234, "CNY") == "-¥12.34"
    assert _minor_amount_label(None, "CNY") == ""
    assert _minor_amount_value(5000, "JPY") == "5000"
    assert _minor_amount_value(1234, "CNY") == "12.34"
    assert _minor_amount_value(-1234, "CNY") == "-12.34"
    assert _minor_amount_value(None, "JPY") == ""


def test_owner_budget_amount_uses_installation_minor_digits() -> None:
    assert _owner_amount_yuan(1234, "JPY") == "1234"
    assert _owner_amount_yuan(1234, "CNY") == "12.34"


@pytest.mark.currency_binding_unbound
def test_confirmed_search_and_reports_use_zero_fraction_home_amounts(
    web_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    identity,
) -> None:
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    get_settings.cache_clear()
    try:
        seed_confirmed_expense_fact(
            currency_code="JPY",
            amount_minor=1234,
            merchant="JPY发布回归",
            category="餐饮",
        )
        month = current_month("Asia/Shanghai")

        confirmed = web_client.get(
            f"/web/confirmed?ledger_id=owner&month={month}"
        )
        assert confirmed.status_code == 200, confirmed.text
        assert f"{month} 共 1 笔，合计 ¥1234。" in confirmed.text
        assert '<span class="amt-main">¥1234</span>' in confirmed.text
        assert '<span class="lday-s">¥1234</span>' in confirmed.text
        assert "¥12.34" not in confirmed.text

        search = web_client.get(
            "/web/search?ledger_id=owner&q=JPY发布回归"
        )
        assert search.status_code == 200, search.text
        assert '<span class="search-amount">¥1,234' in search.text
        assert "<small>JPY</small>" in search.text
        assert "¥12.34" not in search.text

        reports = web_client.get(
            f"/web/reports?ledger_id=owner&month={month}"
        )
        assert reports.status_code == 200, reports.text
        assert '<span class="yuan">¥</span>206' in reports.text
        assert '"amount_yuan": 1234' in reports.text
    finally:
        get_settings.cache_clear()


def test_active_report_scripts_share_the_home_currency_minor_digit_contract() -> None:
    static_root = Path(__file__).resolve().parents[1] / "app" / "static" / "web"
    core = (static_root / "desktop" / "core.js").read_text(encoding="utf-8")
    reports = (static_root / "reports.js").read_text(encoding="utf-8")
    trend = (static_root / "desktop" / "trend-chart.js").read_text(
        encoding="utf-8"
    )
    donut = (static_root / "desktop" / "category-donut.js").read_text(
        encoding="utf-8"
    )

    assert "app.homeMinorToMajor" in core
    assert "app.homeMinorToMajorText" in core
    assert "app.homeMoneyMinor" in core
    assert "Number(cents || 0) / 100" not in reports
    assert "app.homeMoneyMinor(cents)" in reports
    assert "app.homeCurrencySymbol() + compactYuan(cents)" in reports
    assert "root.getAttribute('data-home-currency-symbol')" not in reports
    assert "Math.round(s.amount_yuan)" not in trend
    assert "app.homeMinorToMajor(s.amount_cents)" in trend
    assert "app.homeMoneyMajor(p.data.majorText)" in trend
    assert "app.homeMoneyMajor(p.value || 0)" not in trend
    assert "p.data.amountLabel" in donut
    assert "app.homeMoneyMajor(p.value || 0)" not in donut


def test_web_money_copy_formats_exact_minor_strings_without_number_rounding() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.fail("Node.js is required for the Web money contract")
    core = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "static"
        / "web"
        / "desktop"
        / "core.js"
    )
    script = f"""
const fs = require("fs");
const vm = require("vm");
let digits = "2";
const document = {{
  documentElement: {{
    getAttribute: function (name) {{
      if (name === "data-home-currency-minor-digits") return digits;
      if (name === "data-home-currency-symbol") return "¥";
      return "";
    }},
  }},
}};
const window = {{}};
vm.runInNewContext(
  fs.readFileSync({json.dumps(str(core))}, "utf8"),
  {{ window, document, Intl, Number, BigInt, String, Math, URLSearchParams }}
);
const app = window.TicketboxWeb;
const result = {{
  edge2: app.homeMoneyMinor("9000000000000001"),
  safeMax2: app.homeMoneyMinor("9007199254740991"),
  parts2: app.moneyParts("12.34"),
}};
digits = "0";
result.zero = app.homeMoneyMinor("1234");
result.parts0 = app.moneyParts("1234");
digits = "3";
result.three = app.homeMoneyMinor("1234567");
result.parts3 = app.moneyParts("1234.567");
process.stdout.write(JSON.stringify(result));
"""
    completed = subprocess.run(
        [node, "-e", script],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "edge2": "¥90,000,000,000,000.01",
        "safeMax2": "¥90,071,992,547,409.91",
        "parts2": ["12", "34"],
        "zero": "¥1,234",
        "parts0": ["1234", ""],
        "three": "¥1,234.567",
        "parts3": ["1234", "567"],
    }


def test_web_money_copy_fails_closed_without_canonical_currency_metadata() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.fail("Node.js is required for the Web money contract")
    core = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "static"
        / "web"
        / "desktop"
        / "core.js"
    )
    script = f"""
const fs = require("fs");
const vm = require("vm");
let digits = "2";
let symbol = "¥";
let code = "CNY";
const document = {{
  documentElement: {{
    getAttribute: function (name) {{
      if (name === "data-home-currency-minor-digits") return digits;
      if (name === "data-home-currency-symbol") return symbol;
      if (name === "data-home-currency") return code;
      return null;
    }},
  }},
}};
const window = {{}};
vm.runInNewContext(
  fs.readFileSync({json.dumps(str(core))}, "utf8"),
  {{ window, document, Intl, Number, BigInt, String, Math, URLSearchParams }}
);
const app = window.TicketboxWeb;
const result = {{}};
digits = null;
result.missing = [app.homeCurrencyMinorDigits(), app.homeMinorToMajor("1234"), app.homeMoneyMinor("1234")];
digits = "-1";
result.negative = [app.homeCurrencyMinorDigits(), app.homeMoneyMinor("1234")];
digits = "02";
result.leadingZero = [app.homeCurrencyMinorDigits(), app.homeMoneyMinor("1234")];
digits = "2.0";
result.decimal = [app.homeCurrencyMinorDigits(), app.homeMoneyMinor("1234")];
digits = "2";
symbol = "";
result.codeFallback = app.homeMoneyMinor("1234");
code = "";
result.unknownCode = app.homeMoneyMinor("1234");
process.stdout.write(JSON.stringify(result));
"""
    completed = subprocess.run(
        [node, "-e", script],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "missing": [None, None, "¥金额不可用"],
        "negative": [None, "¥金额不可用"],
        "leadingZero": [None, "¥金额不可用"],
        "decimal": [None, "¥金额不可用"],
        "codeFallback": "CNY 12.34",
        "unknownCode": "币种未知 12.34",
    }
