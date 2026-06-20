"""LocalLlmOcrProvider response → ``OcrResult`` mapping (receipt-specific coercers).

The generic OpenAI-envelope decoding (``extract_message_content`` /
``parse_json_object``) lives in ``app.services.local_llm_vision``; this module
owns only how a receipt's JSON object maps onto the expense draft fields.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import suppress
from datetime import datetime
from typing import Any

from app.config import get_settings
from app.services.category_common import DEFAULT_CATEGORIES, normalize_category
from app.services.ocr_service._models import OcrResult
from app.services.receipt_parse_service import parse_receipt_text
from app.services.time_service import ensure_utc_assuming_local


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
