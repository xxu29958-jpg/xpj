"""Shared local-LLM vision engine tests.

Engine-level coverage that used to live in ``test_expenses_ocr_internals.py``
moved here when the transport / slot-limiter / JSON-envelope decoding were
extracted from the receipt provider into ``app.services.local_llm_vision`` so
the debt-bill parser could share them. The receipt-specific JSON→OcrResult
mapping stays in ``test_expenses_ocr_internals.py``.
"""

from __future__ import annotations

import json
from io import BytesIO
from types import SimpleNamespace
from typing import get_origin, get_type_hints
from unittest.mock import patch
from urllib import error

import pytest

import app.services.local_llm_vision as vision
from app.errors import AppError
from app.recognition_config import resolve_local_llm_base_url
from app.services._json_types import JsonObject, JsonValue
from app.services.local_llm_vision import (
    call_local_llm_vision,
    local_llm_slot,
    parse_json_object,
    post_chat_completion,
)


def _assert_json_boundary_type_hints_resolve() -> None:
    from app.services.background_task_response import BackgroundTaskResponsePayload
    from app.services.budget_advisor_service._providers import OpenAiCompatBudgetAdvisor
    from app.services.learning_service import DecisionDraft, EventDraft
    from app.services.pending_suggestion_service import _loads

    assert get_origin(JsonObject) is dict
    assert JsonValue is not None
    for target in (
        post_chat_completion,
        parse_json_object,
        call_local_llm_vision,
        BackgroundTaskResponsePayload,
        OpenAiCompatBudgetAdvisor._post_chat_completion,
        DecisionDraft,
        EventDraft,
        _loads,
    ):
        assert get_type_hints(target)


def test_local_llm_http_error_body_is_not_exposed_in_app_error() -> None:
    with patch("app.services.local_llm_vision.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = error.HTTPError(
            "http://x",
            500,
            "Server Error",
            {},
            BytesIO(b'{"error":"api_key=sk-local-secret upstream body"}'),
        )
        with pytest.raises(AppError) as exc_info:
            post_chat_completion(
                {"messages": []},
                base_url="http://127.0.0.1:1234/v1",
                timeout_seconds=60,
            )

    assert "sk-local-secret" not in exc_info.value.message
    assert "api_key" not in exc_info.value.message


def test_local_llm_slot_applies_backpressure() -> None:
    with (
        local_llm_slot(max_concurrent=1, queue_timeout_seconds=0),
        pytest.raises(AppError) as exc_info,
        local_llm_slot(max_concurrent=1, queue_timeout_seconds=0),
    ):
        pass

    assert exc_info.value.error == "rate_limited"
    assert exc_info.value.status_code == 429

    with local_llm_slot(max_concurrent=1, queue_timeout_seconds=0):
        pass


@pytest.mark.parametrize(
    "value",
    (
        "http://user@127.0.0.1:1234/v1",
        "http://127.0.0.1:bad/v1",
        "http://127.0.0.1:1234/v1?mode=local",
        "http://127.0.0.1:1234/v1#ignored",
    ),
)
def test_local_llm_base_url_rejects_ambiguous_endpoint_components(value: str) -> None:
    assert resolve_local_llm_base_url(value) == ""


def test_local_llm_base_url_keeps_a_loopback_api_path() -> None:
    assert resolve_local_llm_base_url("http://127.0.0.1:1234/v1/") == "http://127.0.0.1:1234/v1"


def test_local_llm_slot_uses_current_limit_without_parallel_semaphore_escape() -> None:
    with (
        local_llm_slot(max_concurrent=1, queue_timeout_seconds=0),
        local_llm_slot(max_concurrent=2, queue_timeout_seconds=0),
        pytest.raises(AppError) as exc_info,
        local_llm_slot(max_concurrent=2, queue_timeout_seconds=0),
    ):
        pass

    assert exc_info.value.error == "rate_limited"
    assert exc_info.value.status_code == 429


def test_parse_json_object_unwraps_markdown_code_fence() -> None:
    _assert_json_boundary_type_hints_resolve()
    payload = parse_json_object('```json\n{"merchant": "花呗", "installment_count": 12}\n```')

    assert payload == {"merchant": "花呗", "installment_count": 12}


def test_call_local_llm_vision_sends_image_data_url_and_returns_model_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    settings_reads = 0

    class _FakeResponse:
        def __enter__(self) -> _FakeResponse:
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

        def read(self, *args: object) -> bytes:
            content = json.dumps({"merchant": "花呗", "installment_count": 12})
            return json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")

    def _fake_urlopen(req, *args, **kwargs):  # type: ignore[no-untyped-def]
        captured["body"] = req.data
        captured["url"] = req.full_url
        captured["timeout"] = kwargs["timeout"]
        return _FakeResponse()

    def _settings():
        nonlocal settings_reads
        settings_reads += 1
        return SimpleNamespace(
            local_llm_base_url="http://127.0.0.1:1234/v1",
            local_llm_model="vision-test",
            local_llm_timeout_seconds=60,
            local_llm_max_concurrent=2,
            local_llm_queue_timeout_seconds=5,
        )

    # A pinned model id avoids the /models discovery round-trip.
    monkeypatch.setattr(
        vision,
        "get_settings",
        _settings,
    )
    monkeypatch.setattr(vision.request, "urlopen", _fake_urlopen)

    result = call_local_llm_vision(b"\x89PNG-bytes", "image/png", "parse this debt bill")

    assert result == {"merchant": "花呗", "installment_count": 12}
    assert settings_reads == 1
    assert captured["url"] == "http://127.0.0.1:1234/v1/chat/completions"
    assert captured["timeout"] == 60
    body_text = captured["body"].decode("utf-8")
    assert "data:image/png;base64," in body_text
    assert "parse this debt bill" in body_text
