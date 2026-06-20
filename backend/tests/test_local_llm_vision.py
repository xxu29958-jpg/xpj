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
from unittest.mock import patch
from urllib import error

import pytest

import app.services.local_llm_vision as vision
from app.errors import AppError
from app.services.local_llm_vision import (
    call_local_llm_vision,
    local_llm_slot,
    parse_json_object,
    post_chat_completion,
)


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
            post_chat_completion({"messages": []})

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
    payload = parse_json_object('```json\n{"merchant": "花呗", "installment_count": 12}\n```')

    assert payload == {"merchant": "花呗", "installment_count": 12}


def test_call_local_llm_vision_sends_image_data_url_and_returns_model_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, bytes] = {}

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
        return _FakeResponse()

    # A pinned model id avoids the /models discovery round-trip.
    monkeypatch.setattr(
        vision,
        "get_settings",
        lambda: SimpleNamespace(
            local_llm_base_url="http://127.0.0.1:1234/v1",
            local_llm_model="vision-test",
            local_llm_timeout_seconds=60,
            local_llm_max_concurrent=2,
            local_llm_queue_timeout_seconds=5,
        ),
    )
    monkeypatch.setattr(vision.request, "urlopen", _fake_urlopen)

    result = call_local_llm_vision(b"\x89PNG-bytes", "image/png", "parse this debt bill")

    assert result == {"merchant": "花呗", "installment_count": 12}
    body_text = captured["body"].decode("utf-8")
    assert "data:image/png;base64," in body_text
    assert "parse this debt bill" in body_text
