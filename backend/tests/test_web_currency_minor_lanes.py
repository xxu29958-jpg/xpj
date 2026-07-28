"""PR#255 R13-3：/web 四个 ×100 硬编路由的 env-home minor 语义钉。

JPY（零小数 home）下：解析按整数直存、回显不 ÷100、小数输入按口径拒绝；
不再出现 ×100 / ÷100 缩放。CNY 既有口径由各族 web 测试保持。
"""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.errors import AppError
from app.routes.web_bill_split import _cents_to_yuan, _yuan_to_cents
from app.routes.web_income_plans import _parse_yuan
from app.routes.web_rules import _parse_optional_amount_cents


@pytest.fixture
def jpy_env(monkeypatch):
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
    get_settings.cache_clear()


def test_income_parse_and_render_follow_zero_decimal_home(jpy_env) -> None:
    # 解析："1200" → 1200 minor（不 ×100）；回显：1200 minor → "1200"（不 ÷100）。
    assert _parse_yuan("1200", label="收入金额") == 1200
    assert _cents_to_yuan(1200) == "1200"


def test_income_parse_rejects_fraction_under_zero_decimal_home(jpy_env) -> None:
    with pytest.raises(AppError) as excinfo:
        _parse_yuan("12.5", label="收入金额")
    assert excinfo.value.error == "invalid_request"


def test_rules_optional_amount_follow_zero_decimal_home(jpy_env) -> None:
    assert _parse_optional_amount_cents("1200") == 1200
    with pytest.raises(AppError) as excinfo:
        _parse_optional_amount_cents("12.5")
    assert excinfo.value.error == "invalid_request"


def test_bill_split_yuan_to_cents_follows_zero_decimal_home(jpy_env) -> None:
    assert _yuan_to_cents("1200") == 1200
    assert _yuan_to_cents("12.5") is None


def test_web_lanes_still_work_on_cny_default() -> None:
    # CNY 既有口径回归（不随 JPY 切换）：分 = 元 ×100。
    assert _parse_yuan("12.50", label="收入金额") == 1250
    assert _cents_to_yuan(1250) == "12.50"
    assert _parse_optional_amount_cents("12.50") == 1250
    assert _yuan_to_cents("12.50") == 1250
