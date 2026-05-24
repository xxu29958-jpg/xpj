"""v1.1 PR-1 skeleton tests: EmptyBudgetAdvisor noop + factory dispatch.

These lock in the ADR-0036 default behaviour before any provider that
actually calls out to AI ships. Adding more providers must keep these
invariants:

- ``BUDGET_ADVISOR_PROVIDER=empty`` (default) returns ``None``.
- ``BUDGET_ADVISOR_PROVIDER=openai_compat`` raises NotImplementedError
  until the outbound payload guard lands.
"""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.services.budget_advisor_service import (
    BudgetAdvice,
    BudgetAdvisorProvider,
    BudgetInputs,
    BudgetSuggestion,
    CategorySnapshot,
    EmptyBudgetAdvisor,
    FixedExpense,
    HistoricalBaseline,
    IncomePlan,
    MemberRef,
    MerchantSummary,
    MockBudgetAdvisor,
    get_budget_advisor,
)


def _minimal_inputs() -> BudgetInputs:
    return BudgetInputs(
        month="2026-05",
        home_currency="CNY",
        members=[MemberRef(anon_id="member_1")],
        category_breakdown=[
            CategorySnapshot(category="餐饮", amount_cents=120000, count=18),
        ],
        merchant_summary=[
            MerchantSummary(
                anon_id="merchant_001",
                category_class="餐饮",
                amount_cents=42000,
                count=6,
            ),
        ],
        income_plan=[
            IncomePlan(source_type="salary", amount_cents=2_000_000, pay_day=10),
        ],
        fixed_expenses=[
            FixedExpense(
                anon_id="subscription_1",
                category_class="订阅",
                amount_cents=1980,
                frequency="monthly",
            ),
        ],
        historical_baseline=[
            HistoricalBaseline(category="餐饮", median_cents=110000, p75_cents=145000),
        ],
    )


def test_empty_provider_returns_none_for_any_input() -> None:
    advisor = EmptyBudgetAdvisor()
    assert advisor.advise(_minimal_inputs()) is None
    # Also covers a defaulted empty inputs envelope (only required fields).
    assert advisor.advise(BudgetInputs(month="2026-05", home_currency="CNY")) is None


def test_default_factory_returns_empty_advisor() -> None:
    advisor = get_budget_advisor()
    assert isinstance(advisor, EmptyBudgetAdvisor)


def test_explicit_empty_name_returns_empty_advisor() -> None:
    advisor = get_budget_advisor("empty")
    assert isinstance(advisor, EmptyBudgetAdvisor)


def test_unknown_provider_falls_back_to_empty() -> None:
    # Unknown name == "treat as not configured" — never quietly upgrade to a
    # real provider, but also never crash startup. Mirrors get_ocr_provider.
    advisor = get_budget_advisor("does_not_exist")
    assert isinstance(advisor, EmptyBudgetAdvisor)


def test_mock_provider_dispatch() -> None:
    advisor = get_budget_advisor("mock")
    assert isinstance(advisor, MockBudgetAdvisor)


def test_mock_provider_returns_advice_from_top_category() -> None:
    advice = MockBudgetAdvisor().advise(_minimal_inputs())
    assert advice is not None
    assert "餐饮" in advice.summary
    assert advice.confidence == 0.5
    assert len(advice.suggestions) == 1
    suggestion = advice.suggestions[0]
    assert suggestion.category == "餐饮"
    assert suggestion.suggested_amount_cents == 120000  # echoes top category


def test_mock_provider_handles_empty_inputs() -> None:
    advice = MockBudgetAdvisor().advise(
        BudgetInputs(month="2026-05", home_currency="CNY")
    )
    assert advice is not None
    assert advice.confidence == 0.0
    assert advice.suggestions == []


@pytest.mark.parametrize("name", ["openai_compat", "openai-compat", "openai", "OpenAI_Compat"])
def test_openai_compat_requires_base_url_and_model(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # With no env config, openai_compat must refuse to dispatch — never
    # silently fall back to Empty (would hide a real misconfiguration).
    monkeypatch.delenv("BUDGET_ADVISOR_BASE_URL", raising=False)
    monkeypatch.delenv("BUDGET_ADVISOR_MODEL", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(Exception, match="BUDGET_ADVISOR_"):
            get_budget_advisor(name)
    finally:
        get_settings.cache_clear()


def test_default_setting_is_empty() -> None:
    # Settings cache may be populated from a prior test; clear and re-read.
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.budget_advisor_provider == "empty"


def test_protocol_is_structural() -> None:
    # EmptyBudgetAdvisor must satisfy the Protocol without subclassing.
    advisor: BudgetAdvisorProvider = EmptyBudgetAdvisor()
    assert callable(advisor.advise)


def test_advice_dataclass_round_trip() -> None:
    # Authors of follow-up providers will construct these — keep the shape
    # locked so changing BudgetAdvice / BudgetSuggestion is a deliberate edit.
    advice = BudgetAdvice(
        summary="测试建议",
        suggestions=[
            BudgetSuggestion(category="餐饮", suggested_amount_cents=130000, rationale="历史 P75"),
            BudgetSuggestion(category=None, suggested_amount_cents=400000, rationale="月度总额"),
        ],
        confidence=0.82,
    )
    assert advice.summary == "测试建议"
    assert len(advice.suggestions) == 2
    assert advice.suggestions[1].category is None
