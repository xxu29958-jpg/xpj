"""v1.1 PR-3: OpenAiCompatBudgetAdvisor — HTTP transport, response parse,
fail-closed semantics, guard integration.

These tests use ``unittest.mock`` to stub ``urllib.request.urlopen`` so
the suite never actually opens a socket. The advisor's contract is:

- On success: parse OpenAI Chat Completions response → BudgetAdvice.
- On any failure (HTTP error, transport error, malformed JSON, schema
  drift in outbound payload): log + return None. Never raise into the
  budget pipeline (ENGINEERING_RULES §8 / ADR-0036).
- The outbound guard runs *before* the HTTP call (not after) — any
  drift in BudgetInputs surface is caught before bytes leave.
"""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import patch
from urllib import error

import pytest

from app.config import get_settings
from app.errors import AppError
from app.services.budget_advisor_service import (
    BudgetInputs,
    CategorySnapshot,
    OpenAiCompatBudgetAdvisor,
    get_budget_advisor,
)
from app.services.budget_advisor_service._providers import (
    _SYSTEM_PROMPT,
    MAX_ADVICE_RATIONALE_CHARS,
    MAX_ADVICE_SUGGESTIONS,
    MAX_ADVICE_SUMMARY_CHARS,
    MAX_PROVIDER_RESPONSE_BYTES,
    _parse_advice_json,
)
from app.services.category_common import (
    DEFAULT_CATEGORIES,
    LEGACY_CATEGORY_ALIASES,
    normalize_category,
)


def _advisor() -> OpenAiCompatBudgetAdvisor:
    return OpenAiCompatBudgetAdvisor(
        base_url="http://127.0.0.1:11434/v1",
        api_key="",
        model="qwen2.5:7b",
        timeout_seconds=5,
    )


def _inputs() -> BudgetInputs:
    return BudgetInputs(
        month="2026-05",
        home_currency="CNY",
        category_breakdown=[
            CategorySnapshot(category="餐饮", amount_cents=120000, count=18),
            CategorySnapshot(category="交通", amount_cents=42000, count=12),
        ],
    )


# ---------------------------------------------------------------------------
# Happy path: parseable response → BudgetAdvice
# ---------------------------------------------------------------------------


def test_advise_parses_openai_response_into_advice() -> None:
    response_payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "summary": "本月餐饮偏高，建议下月降至 90000。",
                            "suggestions": [
                                {
                                    "category": "餐饮",
                                    "suggested_amount_cents": 90000,
                                    "rationale": "P75 历史基线",
                                },
                                {
                                    "category": None,
                                    "suggested_amount_cents": 400000,
                                    "rationale": "月度总额",
                                },
                            ],
                            "confidence": 0.75,
                        },
                        ensure_ascii=False,
                    )
                }
            }
        ]
    }
    body_bytes = json.dumps(response_payload, ensure_ascii=False).encode("utf-8")

    with patch("app.services.budget_advisor_service._providers.request.urlopen") as mock_urlopen:
        # urlopen used as context manager → __enter__ returns a file-like
        mock_urlopen.return_value.__enter__.return_value = BytesIO(body_bytes)
        advice = _advisor().advise(_inputs())

    assert advice is not None
    assert "餐饮" in advice.summary
    assert advice.confidence == pytest.approx(0.75)
    assert len(advice.suggestions) == 2
    assert advice.suggestions[0].category == "餐饮"
    assert advice.suggestions[0].suggested_amount_cents == 90000
    assert advice.suggestions[1].category is None


def test_advise_handles_response_wrapped_in_markdown_fence() -> None:
    fenced = "```json\n" + json.dumps(
        {"summary": "ok", "suggestions": [], "confidence": 0.9}
    ) + "\n```"
    response_payload = {"choices": [{"message": {"content": fenced}}]}
    body_bytes = json.dumps(response_payload).encode("utf-8")

    with patch("app.services.budget_advisor_service._providers.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = BytesIO(body_bytes)
        advice = _advisor().advise(_inputs())

    assert advice is not None
    assert advice.summary == "ok"
    assert advice.confidence == 0.9


# ---------------------------------------------------------------------------
# Fail-closed: never raise into the budget pipeline
# ---------------------------------------------------------------------------


def test_advise_returns_none_on_http_error() -> None:
    with patch("app.services.budget_advisor_service._providers.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = error.HTTPError(
            "http://x", 500, "Server Error", {}, BytesIO(b"upstream down")
        )
        advice = _advisor().advise(_inputs())
    assert advice is None


def test_http_error_body_is_not_exposed_in_app_error() -> None:
    advisor = _advisor()
    with patch("app.services.budget_advisor_service._providers.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = error.HTTPError(
            "http://x",
            500,
            "Server Error",
            {},
            BytesIO(b'{"error":"secret upstream body token=sk-live-123"}'),
        )
        with pytest.raises(AppError) as exc:
            advisor._post_chat_completion({"messages": []})

    assert "secret upstream body" not in exc.value.message
    assert "sk-live-123" not in exc.value.message
    assert "AI" in exc.value.message


def test_advise_returns_none_on_transport_error() -> None:
    with patch("app.services.budget_advisor_service._providers.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = error.URLError("dns down")
        advice = _advisor().advise(_inputs())
    assert advice is None


def test_provider_response_size_cap_returns_none() -> None:
    response_bytes = b'{"choices":[{"message":{"content":"' + (
        b"x" * MAX_PROVIDER_RESPONSE_BYTES
    ) + b'"}}]}'
    with patch("app.services.budget_advisor_service._providers.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = BytesIO(response_bytes)
        advice = _advisor().advise(_inputs())

    assert advice is None


def test_advise_returns_none_on_malformed_json() -> None:
    response_payload = {"choices": [{"message": {"content": "not json at all"}}]}
    body_bytes = json.dumps(response_payload).encode("utf-8")
    with patch("app.services.budget_advisor_service._providers.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = BytesIO(body_bytes)
        advice = _advisor().advise(_inputs())
    assert advice is None


def test_advise_returns_none_on_unexpected_provider_response_shape() -> None:
    # Missing "choices" entirely.
    body_bytes = json.dumps({"error": "rate limited"}).encode("utf-8")
    with patch("app.services.budget_advisor_service._providers.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = BytesIO(body_bytes)
        advice = _advisor().advise(_inputs())
    assert advice is None


# ---------------------------------------------------------------------------
# Outbound payload contract
# ---------------------------------------------------------------------------


def test_advise_sends_only_allowed_top_level_keys() -> None:
    captured: dict[str, bytes] = {}

    response_payload = {"choices": [{"message": {"content": json.dumps({"summary": "x", "suggestions": [], "confidence": 0.5})}}]}
    response_bytes = json.dumps(response_payload).encode("utf-8")

    def fake_urlopen(req, timeout):  # noqa: ARG001
        captured["body"] = req.data
        # Capture sent payload then return a stub response.
        class _Resp:
            def __enter__(self):
                return BytesIO(response_bytes)

            def __exit__(self, *args):
                return False

        return _Resp()

    with patch("app.services.budget_advisor_service._providers.request.urlopen", fake_urlopen):
        _advisor().advise(_inputs())

    body = json.loads(captured["body"].decode("utf-8"))
    # The advisor wraps inputs as the user message; parse the JSON-stringified user content.
    user_msg = next(m for m in body["messages"] if m["role"] == "user")
    payload = json.loads(user_msg["content"])
    assert set(payload.keys()) == {
        "month",
        "home_currency",
        "category_breakdown",
        "historical_baseline",
    }
    # Verify no real PII fields leaked.
    for cat in payload["category_breakdown"]:
        assert set(cat.keys()) == {"category", "amount_cents", "count"}


# ---------------------------------------------------------------------------
# Factory + config dispatch
# ---------------------------------------------------------------------------


def test_factory_returns_openai_compat_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BUDGET_ADVISOR_PROVIDER", "openai_compat")
    monkeypatch.setenv("BUDGET_ADVISOR_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("BUDGET_ADVISOR_MODEL", "qwen2.5:7b")
    get_settings.cache_clear()
    try:
        advisor = get_budget_advisor()
        assert isinstance(advisor, OpenAiCompatBudgetAdvisor)
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize(
    "alias",
    ["deepseek", "deepseek-chat", "siliconflow", "silicon-flow", "together", "groq"],
)
def test_factory_routes_openai_compatible_aliases(
    alias: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BUDGET_ADVISOR_PROVIDER", alias)
    monkeypatch.setenv("BUDGET_ADVISOR_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("BUDGET_ADVISOR_MODEL", "test-model")
    monkeypatch.setenv("BUDGET_ADVISOR_API_KEY", "test-key")
    get_settings.cache_clear()
    try:
        advisor = get_budget_advisor()
        assert isinstance(advisor, OpenAiCompatBudgetAdvisor)
    finally:
        get_settings.cache_clear()


def test_factory_rejects_openai_compat_without_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BUDGET_ADVISOR_PROVIDER", "openai_compat")
    monkeypatch.delenv("BUDGET_ADVISOR_BASE_URL", raising=False)
    monkeypatch.setenv("BUDGET_ADVISOR_MODEL", "qwen2.5:7b")
    get_settings.cache_clear()
    try:
        with pytest.raises(AppError, match="BUDGET_ADVISOR_BASE_URL"):
            get_budget_advisor()
    finally:
        get_settings.cache_clear()


def test_factory_rejects_openai_compat_without_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BUDGET_ADVISOR_PROVIDER", "openai_compat")
    monkeypatch.setenv("BUDGET_ADVISOR_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.delenv("BUDGET_ADVISOR_MODEL", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(AppError, match="BUDGET_ADVISOR_MODEL"):
            get_budget_advisor()
    finally:
        get_settings.cache_clear()


def test_factory_rejects_public_openai_compat_without_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BUDGET_ADVISOR_PROVIDER", "openai_compat")
    monkeypatch.setenv("BUDGET_ADVISOR_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("BUDGET_ADVISOR_MODEL", "test-model")
    monkeypatch.delenv("BUDGET_ADVISOR_API_KEY", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(AppError, match="BUDGET_ADVISOR_API_KEY"):
            get_budget_advisor()
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize(
    "base_url",
    [
        "ftp://api.example.com/v1",
        "https://user:pass@api.example.com/v1",
        "https://api.example.com:bad/v1",
        "https:///v1",
        "https://api.example.com/v1?token=leak",
        "https://api.example.com/v1#fragment",
    ],
)
def test_factory_rejects_invalid_base_url(
    base_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BUDGET_ADVISOR_PROVIDER", "openai_compat")
    monkeypatch.setenv("BUDGET_ADVISOR_BASE_URL", base_url)
    monkeypatch.setenv("BUDGET_ADVISOR_MODEL", "qwen2.5:7b")
    get_settings.cache_clear()
    try:
        with pytest.raises(AppError, match="BUDGET_ADVISOR_BASE_URL"):
            get_budget_advisor()
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Parser unit tests (private helper, but worth pinning explicit shape rules)
# ---------------------------------------------------------------------------


def test_parser_drops_suggestion_with_invalid_amount() -> None:
    content = json.dumps(
        {
            "summary": "ok",
            "suggestions": [
                {"category": "餐饮", "suggested_amount_cents": "not-a-number", "rationale": "x"},
                {"category": "交通", "suggested_amount_cents": 50000, "rationale": "y"},
            ],
            "confidence": 0.5,
        }
    )
    advice = _parse_advice_json(content)
    assert len(advice.suggestions) == 1
    assert advice.suggestions[0].category == "交通"


def test_parser_clamps_confidence_to_0_1() -> None:
    high = _parse_advice_json(json.dumps({"summary": "s", "suggestions": [], "confidence": 2.5}))
    low = _parse_advice_json(json.dumps({"summary": "s", "suggestions": [], "confidence": -0.5}))
    assert high.confidence == 1.0
    assert low.confidence == 0.0


def test_prompt_category_list_uses_shared_default_categories() -> None:
    for category in DEFAULT_CATEGORIES:
        assert category in _SYSTEM_PROMPT


def test_parser_normalizes_legacy_category_alias() -> None:
    legacy, canonical = next(iter(LEGACY_CATEGORY_ALIASES.items()))
    advice = _parse_advice_json(
        json.dumps(
            {
                "summary": "ok",
                "suggestions": [
                    {
                        "category": legacy,
                        "suggested_amount_cents": 50000,
                        "rationale": "alias",
                    }
                ],
                "confidence": 0.5,
            },
            ensure_ascii=False,
        )
    )
    assert len(advice.suggestions) == 1
    assert advice.suggestions[0].category == canonical
    assert normalize_category(legacy) == canonical


def test_parser_rejects_category_outside_default_catalog() -> None:
    custom_category = "custom-family-category"
    advice = _parse_advice_json(
        json.dumps(
            {
                "summary": "ok",
                "suggestions": [
                    {
                        "category": custom_category,
                        "suggested_amount_cents": 50000,
                        "rationale": "from input",
                    }
                ],
                "confidence": 0.5,
            }
        )
    )
    assert advice.suggestions == []


@pytest.mark.parametrize(
    "api_key",
    [
        "short",
        "valid key",
        "valid\nkey",
        " sk-validkey123",
        "sk-validkey123 ",
    ],
)
def test_factory_rejects_public_api_key_with_unsafe_shape(
    api_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BUDGET_ADVISOR_PROVIDER", "openai_compat")
    monkeypatch.setenv("BUDGET_ADVISOR_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("BUDGET_ADVISOR_MODEL", "test-model")
    monkeypatch.setenv("BUDGET_ADVISOR_API_KEY", api_key)
    get_settings.cache_clear()
    try:
        with pytest.raises(AppError, match="BUDGET_ADVISOR_API_KEY"):
            get_budget_advisor()
    finally:
        get_settings.cache_clear()


def test_parser_caps_text_and_suggestion_count() -> None:
    advice = _parse_advice_json(
        json.dumps(
            {
                "summary": "s" * (MAX_ADVICE_SUMMARY_CHARS + 20),
                "suggestions": [
                    {
                        "category": DEFAULT_CATEGORIES[0],
                        "suggested_amount_cents": index,
                        "rationale": "r" * (MAX_ADVICE_RATIONALE_CHARS + 20),
                    }
                    for index in range(MAX_ADVICE_SUGGESTIONS + 5)
                ],
                "confidence": 0.5,
            },
            ensure_ascii=False,
        )
    )
    assert len(advice.summary) == MAX_ADVICE_SUMMARY_CHARS
    assert len(advice.suggestions) == MAX_ADVICE_SUGGESTIONS
    assert len(advice.suggestions[0].rationale) == MAX_ADVICE_RATIONALE_CHARS
