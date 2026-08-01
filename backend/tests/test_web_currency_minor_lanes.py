"""PR#255 R13-3：/web 四个 ×100 硬编路由的 env-home minor 语义钉。

JPY（零小数 home）下：解析按整数直存、回显不 ÷100、小数输入按口径拒绝；
不再出现 ×100 / ÷100 缩放。CNY 既有口径由各族 web 测试保持。
R15a-3 起补渲染侧：rules 列表金额条件回显、budget-advise breakdown/输入 step/AI 建议表。
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from _web_overview_test_support import create_pending_upload
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
    assert _parse_yuan("1200", currency_code="JPY", label="收入金额") == 1200
    assert _cents_to_yuan(1200, "JPY") == "1200"


def test_income_parse_rejects_fraction_under_zero_decimal_home(jpy_env) -> None:
    with pytest.raises(AppError) as excinfo:
        _parse_yuan("12.5", currency_code="JPY", label="收入金额")
    assert excinfo.value.error == "invalid_request"


def test_rules_optional_amount_follow_zero_decimal_home(jpy_env) -> None:
    assert _parse_optional_amount_cents("1200", currency_code="JPY") == 1200
    with pytest.raises(AppError) as excinfo:
        _parse_optional_amount_cents("12.5", currency_code="JPY")
    assert excinfo.value.error == "invalid_request"


def test_bill_split_yuan_to_cents_follows_zero_decimal_home(jpy_env) -> None:
    assert _yuan_to_cents("1200", "JPY") == 1200
    assert _yuan_to_cents("12.5", "JPY") is None


def test_web_lanes_still_work_on_cny_default() -> None:
    # CNY 既有口径回归（不随 JPY 切换）：分 = 元 ×100。
    assert _parse_yuan("12.50", currency_code="CNY", label="收入金额") == 1250
    assert _cents_to_yuan(1250, "CNY") == "12.50"
    assert _parse_optional_amount_cents("12.50", currency_code="CNY") == 1250
    assert _yuan_to_cents("12.50", "CNY") == 1250


def test_explicit_persisted_currency_parser_ignores_runtime_env_drift(
    jpy_env,
) -> None:
    assert _parse_yuan(
        "12.34",
        currency_code="CNY",
        label="收入金额",
    ) == 1234
    assert _parse_optional_amount_cents(
        "12.34",
        currency_code="CNY",
    ) == 1234


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
    assert "储蓄目标（JPY）" in page.text
    assert "备用金（JPY）" in page.text
    assert "储蓄目标（元）" not in page.text
    assert "备用金（元）" not in page.text
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


def test_zero_fraction_no_js_forms_and_dashboard_share_input_contract(
    jpy_env,
    web_client: TestClient,
    *,
    identity,
) -> None:
    saved = web_client.post(
        "/web/budgets/save",
        data={
            "ledger_id": "owner",
            "month": "2026-05",
            "total_amount_yuan": "1200",
            "category_budget_category": ["餐饮"],
            "category_budget_amount_yuan": ["1200"],
        },
        follow_redirects=False,
    )
    assert saved.status_code in (302, 303), saved.text

    dashboard = web_client.get("/web?ledger_id=owner")
    assert dashboard.status_code == 200, dashboard.text
    assert '<span class="yuan">¥</span>0</div>' in dashboard.text
    assert '<span class="yuan">¥</span>0<span class="decimals">.00</span>' not in dashboard.text

    budgets = web_client.get("/web/budgets?ledger_id=owner&month=2026-05")
    assert budgets.status_code == 200, budgets.text
    assert "月度总预算（JPY · ¥，仅支持整数）" in budgets.text
    assert 'name="total_amount_yuan" value="1200" min="0" step="1"' in budgets.text
    assert "预算（元）" not in budgets.text
    assert 'class="dt-pill danger">超支 ¥0' not in budgets.text

    goals = web_client.get("/web/goals?ledger_id=owner&month=2026-05")
    assert goals.status_code == 200, goals.text
    assert 'name="target_amount_yuan" step="1" min="1" inputmode="numeric"' in goals.text

    rules = web_client.get("/web/rules?ledger_id=owner")
    assert rules.status_code == 200, rules.text
    assert 'name="amount_min_yuan" min="0" step="1" inputmode="numeric"' in rules.text
    assert "金额下限（JPY，可选）" in rules.text


def test_jpy_drawer_and_debt_adjustment_use_zero_fraction_input_contract(
    jpy_env,
    web_client: TestClient,
    *,
    identity,
) -> None:
    expense_id = create_pending_upload(web_client, identity=identity)
    drawer = web_client.get(
        f"/web/expenses/{expense_id}/edit?ledger_id=owner&fragment=1"
    )
    assert drawer.status_code == 200, drawer.text
    assert 'type="number" name="amount_yuan"' in drawer.text
    assert 'min="0" step="1" inputmode="numeric" placeholder="例如 1200"' in drawer.text
    assert 'placeholder="0.00"' not in drawer.text

    created = web_client.post(
        "/api/debts",
        headers={
            **identity.app_headers,
            "Idempotency-Key": str(uuid4()),
        },
        json={
            "direction": "i_owe",
            "counterparty_type": "external",
            "counterparty_label": "JPY 调整提示回归",
            "principal_amount_cents": 1234,
        },
    )
    assert created.status_code == 201, created.text
    detail = web_client.get(f"/web/debts/{created.json()['public_id']}")
    assert detail.status_code == 200, detail.text
    assert 'placeholder="如 -1200"' in detail.text
    assert 'placeholder="如 -10.00"' not in detail.text
