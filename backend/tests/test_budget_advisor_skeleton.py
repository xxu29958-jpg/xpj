"""Budget advisor provider skeleton tests."""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.errors import AppError
from app.services.budget_advisor_service import (
    BudgetAdvice,
    BudgetAdvisorProvider,
    BudgetInputs,
    BudgetSuggestion,
    CategorySnapshot,
    EmptyBudgetAdvisor,
    HistoricalBaseline,
    MockBudgetAdvisor,
    get_budget_advisor,
)
from app.services.category_common import DEFAULT_CATEGORIES


def _minimal_inputs() -> BudgetInputs:
    category = DEFAULT_CATEGORIES[0]
    return BudgetInputs(
        month="2026-05",
        home_currency="CNY",
        category_breakdown=[
            CategorySnapshot(category=category, amount_cents=120000, count=18),
        ],
        historical_baseline=[
            HistoricalBaseline(category=category, median_cents=110000, p75_cents=145000),
        ],
    )


def test_empty_provider_returns_none_for_any_input() -> None:
    advisor = EmptyBudgetAdvisor()
    assert advisor.advise(_minimal_inputs()) is None
    assert advisor.advise(BudgetInputs(month="2026-05", home_currency="CNY")) is None


def test_default_factory_returns_empty_advisor() -> None:
    advisor = get_budget_advisor()
    assert isinstance(advisor, EmptyBudgetAdvisor)


def test_explicit_empty_name_returns_empty_advisor() -> None:
    advisor = get_budget_advisor("empty")
    assert isinstance(advisor, EmptyBudgetAdvisor)


def test_unknown_provider_fails_fast() -> None:
    with pytest.raises(AppError, match="BUDGET_ADVISOR_PROVIDER"):
        get_budget_advisor("does_not_exist")


def test_mock_provider_dispatch() -> None:
    advisor = get_budget_advisor("mock")
    assert isinstance(advisor, MockBudgetAdvisor)


def test_mock_provider_returns_advice_from_top_category() -> None:
    advice = MockBudgetAdvisor().advise(_minimal_inputs())
    assert advice is not None
    assert DEFAULT_CATEGORIES[0] in advice.summary
    assert advice.confidence == 0.5
    assert len(advice.suggestions) == 1
    suggestion = advice.suggestions[0]
    assert suggestion.category == DEFAULT_CATEGORIES[0]
    assert suggestion.suggested_amount_cents == 120000


def test_mock_provider_handles_empty_inputs() -> None:
    advice = MockBudgetAdvisor().advise(
        BudgetInputs(month="2026-05", home_currency="CNY")
    )
    assert advice is not None
    assert advice.confidence == 0.0
    assert advice.suggestions == []


@pytest.mark.parametrize(
    "name",
    [
        "openai_compat",
        "openai-compat",
        "openai",
        "OpenAI_Compat",
        "deepseek",
        "deepseek-chat",
        "siliconflow",
        "silicon-flow",
        "silicon_flow",
        "together",
        "groq",
    ],
)
def test_openai_compat_requires_base_url_and_model(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BUDGET_ADVISOR_BASE_URL", raising=False)
    monkeypatch.delenv("BUDGET_ADVISOR_MODEL", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(Exception, match="BUDGET_ADVISOR_"):
            get_budget_advisor(name)
    finally:
        get_settings.cache_clear()


def test_default_setting_is_empty() -> None:
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.budget_advisor_provider == "empty"


def test_protocol_is_structural() -> None:
    advisor: BudgetAdvisorProvider = EmptyBudgetAdvisor()
    assert callable(advisor.advise)


def test_advice_dataclass_round_trip() -> None:
    advice = BudgetAdvice(
        summary="test advice",
        suggestions=[
            BudgetSuggestion(
                category=DEFAULT_CATEGORIES[0],
                suggested_amount_cents=130000,
                rationale="historical P75",
            ),
            BudgetSuggestion(
                category=None,
                suggested_amount_cents=400000,
                rationale="monthly total",
            ),
        ],
        confidence=0.82,
    )
    assert advice.summary == "test advice"
    assert len(advice.suggestions) == 2
    assert advice.suggestions[1].category is None
