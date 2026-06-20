"""ADR-0015 OCR Provider pipeline: 4 provider implementations + factory.

The ``local_llm`` provider drives the self-hosted vision model through the
shared ``app.services.local_llm_vision`` engine (the same engine the debt-bill
parser uses); this module owns only the receipt-specific prompt + the
receipt JSON→``OcrResult`` mapping.
"""

from __future__ import annotations

import mimetypes

from app.config import get_settings
from app.errors import AppError
from app.models import Expense
from app.services.category_common import DEFAULT_CATEGORIES
from app.services.file_service import resolve_protected_image
from app.services.local_llm_vision import call_local_llm_vision, require_local_llm_base_url
from app.services.ocr_service._llm_parsing import _result_from_llm_json
from app.services.ocr_service._merge import _merge_result_with_text_parse
from app.services.ocr_service._models import OcrProvider, OcrResult
from app.services.receipt_parse_service import parse_receipt_text


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
        # Fail fast before reading the image off disk when config rejected the URL.
        require_local_llm_base_url(settings.local_llm_base_url)
        image_path, media_type = resolve_protected_image(expense.image_path, expense.tenant_id)
        image_bytes = image_path.read_bytes()
        media_type = media_type or mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
        parsed_json = call_local_llm_vision(image_bytes, media_type, _local_llm_prompt_text())
        return _result_from_llm_json(parsed_json, timezone_name=timezone_name)


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


def get_ocr_provider(provider_name: str | None = None) -> OcrProvider:
    name = (provider_name or get_settings().ocr_provider).strip().lower()
    if name == "mock":
        return MockOcrProvider()
    if name in {"rapidocr", "rapid_ocr"}:
        return RapidOcrProvider()
    if name in {"local_llm", "local_vlm", "vlm"}:
        return LocalLlmOcrProvider()
    return EmptyOcrProvider()
