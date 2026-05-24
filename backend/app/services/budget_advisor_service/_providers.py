"""Budget advisor provider implementations + factory.

ADR-0036 pins exactly two intended providers:

- ``EmptyBudgetAdvisor`` — default; never calls an AI service; returns
  ``None``. Core budgeting must still produce a usable result with this
  provider in place (AI is suggestion-only, not authoritative).
- ``OpenAiCompatBudgetAdvisor`` — unified local + cloud provider speaking
  the OpenAI Chat Completions protocol. Lands in a follow-up PR; selecting
  it today raises ``NotImplementedError`` so the env switch is wired but
  cannot accidentally exfiltrate data before the outbound guard ships.
"""

from __future__ import annotations

from app.config import get_settings
from app.services.budget_advisor_service._models import (
    BudgetAdvice,
    BudgetAdvisorProvider,
    BudgetInputs,
    BudgetSuggestion,
)


class EmptyBudgetAdvisor:
    """No-op provider. Returns None — caller treats absence of advice as
    "use local rules only", which is the documented zero-config path."""

    def advise(self, inputs: BudgetInputs) -> BudgetAdvice | None:
        return None


class MockBudgetAdvisor:
    """Deterministic test / dev provider — never calls an AI service.

    Synthesises a ``BudgetAdvice`` directly from ``inputs`` so callers can
    exercise the suggestion-render pipeline (UI, audit log, "采纳/手改"
    flow) without standing up a model. Required by ENGINEERING_RULES §8
    ("at least empty / mock implementations" for every provider).
    """

    def advise(self, inputs: BudgetInputs) -> BudgetAdvice | None:
        if not inputs.category_breakdown:
            return BudgetAdvice(summary="本月暂无消费数据可供建议。", confidence=0.0)
        top = max(inputs.category_breakdown, key=lambda row: row.amount_cents)
        return BudgetAdvice(
            summary=f"模拟建议：{top.category} 是本月占比最高的分类。",
            suggestions=[
                BudgetSuggestion(
                    category=top.category,
                    suggested_amount_cents=top.amount_cents,
                    rationale="mock 建议＝当前实际值（dev / test 用，无 AI 调用）",
                ),
            ],
            confidence=0.5,
        )


def get_budget_advisor(provider_name: str | None = None) -> BudgetAdvisorProvider:
    """Resolve a provider by name. Defaults to ``empty`` per ADR-0036.

    ``openai_compat`` is reserved for the next PR (will require the outbound
    payload guard to be in place). Until then, selecting it raises
    NotImplementedError so the env var is forward-compatible but cannot
    actually call out.
    """

    name = (provider_name or get_settings().budget_advisor_provider).strip().lower()
    if name == "mock":
        return MockBudgetAdvisor()
    if name in {"openai_compat", "openai-compat", "openai"}:
        raise NotImplementedError(
            "OpenAiCompatBudgetAdvisor ships in v1.1 PR-2 once the outbound "
            "payload guard lands. Keep BUDGET_ADVISOR_PROVIDER=empty until then."
        )
    return EmptyBudgetAdvisor()
