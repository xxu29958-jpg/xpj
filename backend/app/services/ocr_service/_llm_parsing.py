"""LocalLlmOcrProvider response parsing — pure helpers + JSON decoders (leaf)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from contextlib import suppress
from datetime import datetime
from typing import Any

from app.config import get_settings
from app.errors import AppError
from app.services.category_common import DEFAULT_CATEGORIES, normalize_category
from app.services.ocr_service._models import OcrResult
from app.services.receipt_parse_service import parse_receipt_text
from app.services.time_service import ensure_utc_assuming_local


def _extract_message_content(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise AppError("server_error", "本地大模型返回格式不正确。", status_code=500)
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
    raise AppError("server_error", "本地大模型没有返回文本内容。", status_code=500)


def _parse_json_object(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = rewrap_code_fence(cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise AppError("server_error", "本地大模型没有返回 JSON。", status_code=500)
    try:
        payload = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AppError("server_error", "本地大模型返回的 JSON 无法解析。", status_code=500) from exc
    if not isinstance(payload, dict):
        raise AppError("server_error", "本地大模型返回的 JSON 不是对象。", status_code=500)
    return payload


def rewrap_code_fence(content: str) -> str:
    lines = content.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _result_from_llm_json(payload: Mapping[str, object], timezone_name: str | None = None) -> OcrResult:
    raw_text = str(payload.get("raw_text") or "")
    confidence = _coerce_float(payload.get("confidence"))
    amount_cents = _coerce_amount_cents(payload.get("amount_cents"))
    merchant = _coerce_optional_text(payload.get("merchant"))
    expense_time = _coerce_datetime(payload.get("expense_time"), timezone_name=timezone_name)
    category = _coerce_category(payload.get("category"))
    return OcrResult(
        raw_text=raw_text,
        confidence=confidence,
        amount_cents=amount_cents,
        merchant=merchant,
        expense_time=expense_time,
        category=category,
    )


def _coerce_optional_text(value: Any) -> str | None:
    coerced: str | None = None
    if value is not None:
        text = str(value).strip()
        if text and text.lower() != "null":
            coerced = text
    return coerced


def _coerce_category(value: Any) -> str | None:
    category: str | None = None
    text = _coerce_optional_text(value)
    if text is not None:
        normalized = normalize_category(text)
        if normalized in DEFAULT_CATEGORIES:
            category = normalized
    return category


def _coerce_int(value: Any) -> int | None:
    coerced: int | None = None
    if value is not None:
        with suppress(TypeError, ValueError):
            coerced = int(value)
    return coerced


def _coerce_amount_cents(value: Any) -> int | None:
    amount_cents: int | None = None
    amount = _coerce_int(value)
    if amount is not None and amount > 0:
        amount_cents = amount
    return amount_cents


def _coerce_float(value: Any) -> float | None:
    coerced: float | None = None
    if value is not None:
        with suppress(TypeError, ValueError):
            coerced = max(0.0, min(1.0, float(value)))
    return coerced


def _coerce_datetime(value: Any, timezone_name: str | None = None) -> datetime | None:
    text = _coerce_optional_text(value)
    if text is None:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return parse_receipt_text(f"时间：{text}", timezone_name=timezone_name).expense_time
    resolved_timezone = (timezone_name or "").strip() or get_settings().ocr_default_timezone
    return ensure_utc_assuming_local(parsed, resolved_timezone)
