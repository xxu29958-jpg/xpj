"""PR#255 R13-3：/web 四个 ×100 硬编路由的 env-home minor 语义钉。

JPY（零小数 home）下：解析按整数直存、回显不 ÷100、小数输入按口径拒绝；
不再出现 ×100 / ÷100 缩放。CNY 既有口径由各族 web 测试保持。
R15a-3 起补渲染侧：rules 列表金额条件回显、budget-advise breakdown/输入 step/AI 建议表。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings, reset_settings_cache
from app.errors import AppError
from app.routes.web_bill_split import _cents_to_yuan, _yuan_to_cents
from app.routes.web_income_plans import _parse_yuan
from app.routes.web_rules import _parse_optional_amount_cents
from app.services.budget_advisor_service import _providers as providers_module


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
    assert _cents_to_yuan(1200, "JPY") == "1200"


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
    assert _yuan_to_cents("1200", "JPY") == 1200
    assert _yuan_to_cents("12.5", "JPY") is None


def test_web_lanes_still_work_on_cny_default() -> None:
    # CNY 既有口径回归（不随 JPY 切换）：分 = 元 ×100。
    assert _parse_yuan("12.50", label="收入金额") == 1250
    assert _cents_to_yuan(1250, "CNY") == "12.50"
    assert _parse_optional_amount_cents("12.50") == 1250
    assert _yuan_to_cents("12.50", "CNY") == 1250


@pytest.fixture
def live_provider_env(monkeypatch):
    # 镜像 test_web_budget_advise.py：假 provider + 免限流，供建议表渲染钉走通 POST 路径。
    monkeypatch.setenv("BUDGET_ADVISOR_PROVIDER", "deepseek")
    monkeypatch.setenv("BUDGET_ADVISOR_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("BUDGET_ADVISOR_MODEL", "test-model")
    monkeypatch.setenv("BUDGET_ADVISOR_API_KEY", "test-key")
    monkeypatch.setenv("BUDGET_ADVISOR_LIVE_MIN_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("BUDGET_ADVISOR_LIVE_DAILY_CALL_LIMIT", "0")
    monkeypatch.setenv("BUDGET_ADVISOR_OWNER_CONFIRMED", "true")
    reset_settings_cache()
    yield monkeypatch
    reset_settings_cache()


def _patch_provider_suggestion(monkeypatch, cents: int) -> None:
    def fake_post(self, body):
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"summary":"ok","suggestions":[{"category":"餐饮",'
                            f'"suggested_amount_cents":{cents},"rationale":"稳定"'
                            '}],"confidence":0.5}'
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(
        providers_module.OpenAiCompatBudgetAdvisor,
        "_post_chat_completion",
        fake_post,
    )


def test_rules_page_render_follows_zero_decimal_home(jpy_env, web_client: TestClient, *, identity) -> None:
    # R15a-3：JPY env 下 rules 列表金额条件回显零缩放 —— 1200 minor 亮 "¥1200"，不 ÷100 成 "¥12.00"。
    resp = web_client.post(
        "/web/rules/create",
        data={
            "keyword": "交通",
            "category": "交通",
            "amount_min_yuan": "1200",
            "ledger_id": "owner",
        },
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303), resp.text

    page = web_client.get("/web/rules?ledger_id=owner")
    assert page.status_code == 200, page.text
    assert "≥ ¥1200" in page.text
    assert "¥12.00" not in page.text


def test_budget_advise_render_follows_zero_decimal_home(jpy_env, web_client: TestClient, *, identity) -> None:
    # R15a-3：JPY env 下 advise breakdown 回显零缩放 + 输入 step 走零小数元数据。
    page = web_client.get(
        "/web/budget-advise?ledger_id=owner&month=2026-05&savings_target_yuan=1200",
    )
    assert page.status_code == 200, page.text
    assert "¥1200 储蓄目标" in page.text
    assert "¥12.00 储蓄目标" not in page.text
    assert 'step="1"' in page.text


def test_budget_advise_suggestion_table_follows_zero_decimal_home(
    jpy_env, web_client: TestClient, live_provider_env, monkeypatch, *, identity
) -> None:
    # R15a-3：AI 建议表回显零缩放 —— suggested_amount_cents=1200 亮 "¥1200"，不 ÷100。
    _patch_provider_suggestion(monkeypatch, 1200)

    page = web_client.post(
        "/web/budget-advise",
        data={"ledger_id": "owner", "month": "2026-05", "run_advise": "true"},
    )
    assert page.status_code == 200, page.text
    assert "¥1200" in page.text
    assert "¥12.00" not in page.text


def test_render_lanes_still_work_on_cny_default(web_client: TestClient, *, identity) -> None:
    # CNY 回归：渲染侧分→元 ÷100 两位口径不变。
    resp = web_client.post(
        "/web/rules/create",
        data={
            "keyword": "餐饮",
            "category": "餐饮",
            "amount_min_yuan": "12.50",
            "ledger_id": "owner",
        },
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303), resp.text

    page = web_client.get("/web/rules?ledger_id=owner")
    assert page.status_code == 200, page.text
    assert "≥ ¥12.50" in page.text

    advise = web_client.get(
        "/web/budget-advise?ledger_id=owner&month=2026-05&savings_target_yuan=12",
    )
    assert advise.status_code == 200, advise.text
    assert "¥12.00 储蓄目标" in advise.text
    assert 'step="0.01"' in advise.text


def test_read_paths_follow_binding_marker_over_env(web_client: TestClient, monkeypatch, *, identity) -> None:
    # 遗留 U10+U20：读路径口径标记优先 —— 标记=JPY + env=CNY（漂移窗口，写面门已拒）时
    # income 合计与 advise breakdown 按 JPY 渲染（"1200"），不跟 env ÷100/补两位。
    from app.database import SessionLocal
    from app.models import AppMeta, MonthlyIncomePlan
    from app.services.currency_binding_service import INSTALLATION_HOME_CURRENCY_KEY
    from app.services.time_service import now_utc

    with SessionLocal() as db:
        db.add(AppMeta(key=INSTALLATION_HOME_CURRENCY_KEY, value="JPY", updated_at=now_utc()))
        db.add(
            MonthlyIncomePlan(
                tenant_id="owner",
                label="工资",
                source_type="salary",
                amount_cents=1200,
                pay_day=10,
                status="active",
            )
        )
        db.commit()
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "CNY")
    get_settings.cache_clear()
    try:
        page = web_client.get("/web/income-plans?ledger_id=owner")
        assert page.status_code == 200, page.text
        assert "1200" in page.text
        assert "12.00" not in page.text

        advise = web_client.get(
            "/web/budget-advise?ledger_id=owner&month=2026-05&savings_target_yuan=1200",
        )
        assert advise.status_code == 200, advise.text
        assert "¥1200 储蓄目标" in advise.text
        assert "¥12.00 储蓄目标" not in advise.text
    finally:
        monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
        get_settings.cache_clear()


def test_rules_form_controls_follow_env_minor_semantics(jpy_env, web_client: TestClient, *, identity) -> None:
    # 遗留 U17：JPY env 下 rules 金额条件控件 step=1、整数占位、符号标签（无小数位）。
    page = web_client.get("/web/rules?ledger_id=owner")
    assert page.status_code == 200, page.text
    assert 'step="1"' in page.text
    assert "如：1200" in page.text
    assert 'step="0.01"' not in page.text
    assert "（¥，可选）" in page.text


def test_rules_form_controls_stay_cny_default(web_client: TestClient, *, identity) -> None:
    # CNY 回归：step=0.01、两位小数占位、「元」标签。
    page = web_client.get("/web/rules?ledger_id=owner")
    assert page.status_code == 200, page.text
    assert 'step="0.01"' in page.text
    assert "如：12.34" in page.text
    assert "（元，可选）" in page.text


def test_read_path_symbol_follows_binding_marker_over_env(web_client: TestClient, monkeypatch, *, identity) -> None:
    # #258-R2 项3：标记=USD + env=CNY 时 income 合计与 advise breakdown 符号随标记（$ 不冠 ¥）。
    from app.database import SessionLocal
    from app.models import AppMeta, MonthlyIncomePlan
    from app.services.currency_binding_service import INSTALLATION_HOME_CURRENCY_KEY
    from app.services.time_service import now_utc

    with SessionLocal() as db:
        db.add(AppMeta(key=INSTALLATION_HOME_CURRENCY_KEY, value="USD", updated_at=now_utc()))
        db.add(
            MonthlyIncomePlan(
                tenant_id="owner",
                label="工资",
                source_type="salary",
                amount_cents=123456,
                pay_day=10,
                status="active",
            )
        )
        db.commit()
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "CNY")
    get_settings.cache_clear()
    try:
        page = web_client.get("/web/income-plans?ledger_id=owner")
        assert page.status_code == 200, page.text
        assert "$1234.56" in page.text
        assert "¥1234.56" not in page.text

        advise = web_client.get(
            "/web/budget-advise?ledger_id=owner&month=2026-05&savings_target_yuan=1234.56",
        )
        assert advise.status_code == 200, advise.text
        assert "$1234.56 储蓄目标" in advise.text
        assert "¥1234.56 储蓄目标" not in advise.text
    finally:
        monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
        get_settings.cache_clear()
