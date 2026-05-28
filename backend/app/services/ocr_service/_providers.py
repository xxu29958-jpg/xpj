"""ADR-0015 OCR Provider pipeline: 4 provider implementations + factory."""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import threading
from contextlib import contextmanager
from time import monotonic
from typing import Any
from urllib import error, request

from app.config import get_settings
from app.errors import AppError
from app.models import Expense
from app.services.category_common import DEFAULT_CATEGORIES
from app.services.file_service import resolve_protected_image
from app.services.ocr_service._llm_parsing import (
    _extract_message_content,
    _parse_json_object,
    _result_from_llm_json,
)
from app.services.ocr_service._merge import _merge_result_with_text_parse
from app.services.ocr_service._models import OcrProvider, OcrResult
from app.services.receipt_parse_service import parse_receipt_text

logger = logging.getLogger(__name__)


class _LocalLlmSlotLimiter:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._active_slots = 0

    def acquire(self, max_concurrent: int, queue_timeout_seconds: float) -> None:
        limit = max(1, int(max_concurrent or 1))
        timeout = max(0.0, float(queue_timeout_seconds))
        deadline = monotonic() + timeout
        with self._condition:
            while limit <= self._active_slots:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise AppError(
                        "rate_limited",
                        "本地大模型识别队列繁忙，请稍后再试。",
                        status_code=429,
                    )
                self._condition.wait(remaining)
            self._active_slots += 1

    def release(self) -> None:
        with self._condition:
            if self._active_slots > 0:
                self._active_slots -= 1
            self._condition.notify_all()


_LOCAL_LLM_SLOT_LIMITER = _LocalLlmSlotLimiter()


class EmptyOcrProvider:
    def extract(self, expense: Expense, timezone_name: str | None = None) -> OcrResult:
        # v1.2 OCR single-source migration (step 5): no longer reads
        # ``expense.raw_text``. The "empty" provider is a placeholder
        # used when no real OCR pipeline is configured — its job is
        # to return a confidence-only result, not to surface stale
        # column data as if it were a fresh OCR pass.
        return OcrResult(raw_text="", confidence=expense.confidence)


class MockOcrProvider:
    def extract(self, expense: Expense, timezone_name: str | None = None) -> OcrResult:
        # v1.2 OCR single-source migration (step 5): the canned
        # mock-receipt body is the only input now. The previous
        # ``expense.raw_text or <canned>`` branch let callers smuggle
        # raw text in through the deprecated column; with that gone,
        # the mock provider behaves the same regardless of any
        # historical column value.
        raw_text = (
            "中国建设银行\n交易提醒\n交易时间：2026年5月4日 16:23:25\n交易金额：18.51（人民币）"
        )
        parsed = parse_receipt_text(raw_text, timezone_name=timezone_name)
        return OcrResult(
            raw_text=raw_text,
            confidence=parsed.confidence if parsed.confidence is not None else 0.0,
            amount_cents=parsed.amount_cents,
            merchant=parsed.merchant,
            expense_time=parsed.expense_time,
            category=parsed.category,
        )


class RapidOcrProvider:
    def extract(self, expense: Expense, timezone_name: str | None = None) -> OcrResult:
        try:
            from rapidocr import RapidOCR  # type: ignore[import-not-found]
        except ImportError as exc:
            raise AppError(
                "server_error",
                "本地 RapidOCR 未安装。请先安装 backend/requirements-ocr.txt。",
                status_code=500,
            ) from exc

        image_path, _ = resolve_protected_image(expense.image_path, expense.tenant_id)
        try:
            result = RapidOCR()(str(image_path))
        except Exception as exc:
            raise AppError("server_error", "本地 OCR 识别失败。", status_code=500) from exc

        texts = [text.strip() for text in (result.txts or ()) if text and text.strip()]
        raw_text = "\n".join(texts)
        scores = [float(score) for score in (result.scores or ()) if score is not None]
        confidence = (sum(scores) / len(scores)) if scores else None
        return _merge_result_with_text_parse(
            OcrResult(raw_text=raw_text, confidence=confidence),
            parsed_confidence=confidence,
            timezone_name=timezone_name,
        )


class LocalLlmOcrProvider:
    def extract(self, expense: Expense, timezone_name: str | None = None) -> OcrResult:
        settings = get_settings()
        _require_local_llm_base_url(settings.local_llm_base_url)
        image_path, media_type = resolve_protected_image(expense.image_path, expense.tenant_id)
        image_bytes = image_path.read_bytes()
        media_type = media_type or mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
        encoded = base64.b64encode(image_bytes).decode("ascii")
        model = settings.local_llm_model or self._first_available_model(settings.local_llm_base_url)
        payload = {
            "model": model,
            "temperature": 0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": _local_llm_prompt_text(),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{media_type};base64,{encoded}"},
                        },
                    ],
                }
            ],
        }
        with _local_llm_slot(
            settings.local_llm_max_concurrent,
            settings.local_llm_queue_timeout_seconds,
        ):
            response = self._post_chat_completion(payload)
        content = _extract_message_content(response)
        parsed_json = _parse_json_object(content)
        return _result_from_llm_json(parsed_json, timezone_name=timezone_name)

    def _first_available_model(self, base_url: str) -> str:
        endpoint = f"{base_url}/models"
        req = request.Request(endpoint, method="GET")
        try:
            with request.urlopen(req, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, error.URLError, json.JSONDecodeError) as exc:
            raise AppError("server_error", "本地大模型服务不可用。", status_code=500) from exc

        models = payload.get("data") if isinstance(payload, dict) else None
        if not models:
            raise AppError("server_error", "本地大模型服务没有可用模型。", status_code=500)
        model_id = models[0].get("id") if isinstance(models[0], dict) else None
        if not model_id:
            raise AppError("server_error", "本地大模型服务模型列表格式不正确。", status_code=500)
        return str(model_id)

    def _post_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        settings = get_settings()
        endpoint = f"{settings.local_llm_base_url}/chat/completions"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            endpoint,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with request.urlopen(req, timeout=settings.local_llm_timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail_bytes = exc.read(4096)
            logger.warning(
                "local_llm_ocr: HTTP error status=%s reason=%s detail_bytes=%s",
                exc.code,
                exc.reason,
                len(detail_bytes),
            )
            raise AppError("server_error", "本地大模型识别失败。", status_code=500) from exc
        except (OSError, error.URLError, json.JSONDecodeError) as exc:
            raise AppError("server_error", "本地大模型服务不可用。", status_code=500) from exc


def _require_local_llm_base_url(base_url: str) -> None:
    """Refuse to call the local LLM when config rejected the URL.

    Empty value here means ``_resolve_local_llm_base_url`` (in app.config)
    treated the configured URL as non-loopback and dropped it. We surface that
    as a clear, actionable error rather than silently sending uploaded receipts
    to whatever the env variable pointed at.
    """

    if not base_url:
        raise AppError(
            "server_error",
            "LOCAL_LLM_BASE_URL 必须是本机回环地址（127.0.0.1 / ::1 / localhost）。",
            status_code=500,
        )


def _local_llm_prompt_text() -> str:
    categories = "/".join(DEFAULT_CATEGORIES)
    return (
        "You are Xiaopiaojia's local receipt OCR parser. Extract bill fields "
        "from the image and return JSON only, with no explanation. Fields: "
        "amount_cents(int|null, minor units; must be greater than 0 when present; "
        "use null when unknown, never 0), merchant(string|null), "
        "expense_time(string|null, ISO 8601; assume Beijing time if the image has "
        f"no timezone), category(string|null, one of: {categories}), "
        "raw_text(string), confidence(number 0-1). Do not return source; the "
        "server owns the source field."
    )


@contextmanager
def _local_llm_slot(max_concurrent: int, queue_timeout_seconds: float):
    _LOCAL_LLM_SLOT_LIMITER.acquire(max_concurrent, queue_timeout_seconds)
    try:
        yield
    finally:
        _LOCAL_LLM_SLOT_LIMITER.release()


def get_ocr_provider(provider_name: str | None = None) -> OcrProvider:
    name = (provider_name or get_settings().ocr_provider).strip().lower()
    if name == "mock":
        return MockOcrProvider()
    if name in {"rapidocr", "rapid_ocr"}:
        return RapidOcrProvider()
    if name in {"local_llm", "local_vlm", "vlm"}:
        return LocalLlmOcrProvider()
    return EmptyOcrProvider()
