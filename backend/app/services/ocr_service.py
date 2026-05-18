from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
import json
import mimetypes
from typing import Any, Protocol
from urllib import error, request

from app.config import get_settings
from app.errors import AppError
from app.fx_constants import FX_SOURCE_BASE, FX_STATUS_READY
from app.models import Expense
from app.services.category_service import normalize_category
from app.services.file_service import resolve_protected_image
from app.services.exchange_rate_service import default_rate_date, home_currency_code
from app.services.receipt_parse_service import parse_receipt_text
from app.services.time_service import ensure_utc, ensure_utc_assuming_local


@dataclass(frozen=True)
class OcrResult:
    raw_text: str
    confidence: float | None
    amount_cents: int | None = None
    merchant: str | None = None
    expense_time: datetime | None = None
    category: str | None = None


class OcrProvider(Protocol):
    def extract(self, expense: Expense, timezone_name: str | None = None) -> OcrResult:
        ...


OCR_DRAFT_FIELDS = frozenset({"amount_cents", "merchant", "category", "expense_time"})
LEGACY_AUTO_OCR_WINDOW = timedelta(minutes=5)


class EmptyOcrProvider:
    def extract(self, expense: Expense, timezone_name: str | None = None) -> OcrResult:
        return OcrResult(raw_text=expense.raw_text or "", confidence=expense.confidence)


class MockOcrProvider:
    def extract(self, expense: Expense, timezone_name: str | None = None) -> OcrResult:
        raw_text = (
            expense.raw_text
            or "中国建设银行\n交易提醒\n交易时间：2026年5月4日 16:23:25\n交易金额：18.51（人民币）"
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
        image_path, media_type = resolve_protected_image(expense.image_path, expense.tenant_id)
        image_bytes = image_path.read_bytes()
        media_type = media_type or mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
        encoded = base64.b64encode(image_bytes).decode("ascii")
        settings = get_settings()
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
                            "text": (
                                "你是小票夹的本地账单识别器。请从截图中提取账单信息，只返回 JSON，"
                                "不要解释。字段：amount_cents(int|null, 分), merchant(string|null), "
                                "expense_time(string|null, ISO 8601, 如果截图没有时区则按北京时间), "
                                "category(string|null, 餐饮/交通/购物/娱乐/医疗/教育/住房/通讯/AI订阅/数码/游戏/生活/其他), "
                                "raw_text(string), confidence(number 0-1)。如果不确定填 null。"
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{media_type};base64,{encoded}"},
                        },
                    ],
                }
            ],
        }
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
            detail = exc.read().decode("utf-8", errors="replace")
            raise AppError("server_error", f"本地大模型识别失败：{detail[:160]}", status_code=500) from exc
        except (OSError, error.URLError, json.JSONDecodeError) as exc:
            raise AppError("server_error", "本地大模型服务不可用。", status_code=500) from exc


def get_ocr_provider(provider_name: str | None = None) -> OcrProvider:
    name = (provider_name or get_settings().ocr_provider).strip().lower()
    if name == "mock":
        return MockOcrProvider()
    if name in {"rapidocr", "rapid_ocr"}:
        return RapidOcrProvider()
    if name in {"local_llm", "local_vlm", "vlm"}:
        return LocalLlmOcrProvider()
    return EmptyOcrProvider()


def retry_ocr(expense: Expense, provider: OcrProvider | None = None, timezone_name: str | None = None) -> Expense:
    active_provider = provider or get_ocr_provider()
    result = active_provider.extract(expense, timezone_name=timezone_name)
    apply_ocr_result(expense, result, timezone_name=timezone_name)
    return expense


def ocr_draft_fields(expense: Expense) -> set[str]:
    payload = expense.ocr_draft_fields
    if not payload:
        return _legacy_pending_ocr_draft_fields(expense)
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError:
        return set()
    if not isinstance(decoded, list):
        return set()
    return {str(item) for item in decoded if str(item) in OCR_DRAFT_FIELDS}


def clear_ocr_draft_fields(expense: Expense, fields: set[str] | list[str] | tuple[str, ...]) -> None:
    current = ocr_draft_fields(expense)
    updated = current.difference(fields)
    _write_ocr_draft_fields(expense, updated)


def collect_auto_ocr_results(expense: Expense, timezone_name: str | None = None) -> list[OcrResult]:
    """Run configured OCR providers and return draft results without mutating the expense."""
    settings = get_settings()
    if not settings.ocr_auto_run:
        return []

    try:
        primary_result = get_ocr_provider(settings.ocr_provider).extract(expense, timezone_name=timezone_name)
        results = [primary_result]

        draft = Expense(
            amount_cents=expense.amount_cents,
            merchant=expense.merchant,
            category=expense.category,
            raw_text=expense.raw_text,
            confidence=expense.confidence,
            expense_time=expense.expense_time,
            ocr_draft_fields=expense.ocr_draft_fields,
            status="pending",
        )
        apply_ocr_result(draft, primary_result, timezone_name=timezone_name)
        if _needs_fallback(draft) and settings.ocr_fallback_provider not in {"", "empty", settings.ocr_provider}:
            results.append(get_ocr_provider(settings.ocr_fallback_provider).extract(expense, timezone_name=timezone_name))
        return results
    except Exception:
        # Upload must stay reliable. Manual retry exposes provider errors to the user.
        return []


def run_auto_ocr(expense: Expense, timezone_name: str | None = None) -> None:
    for result in collect_auto_ocr_results(expense, timezone_name=timezone_name):
        apply_ocr_result(expense, result, timezone_name=timezone_name)


def apply_ocr_result(expense: Expense, result: OcrResult, timezone_name: str | None = None) -> None:
    if expense.status != "pending":
        return

    parsed = parse_receipt_text(result.raw_text, timezone_name=timezone_name)
    merged = _merge_result_with_text_parse(result, parsed_confidence=parsed.confidence, timezone_name=timezone_name)
    draft_fields = ocr_draft_fields(expense)
    applied_fields: set[str] = set()

    expense.raw_text = merged.raw_text
    expense.confidence = _best_confidence(merged.confidence, parsed.confidence, expense.confidence)
    if (
        _can_apply_ocr_field("amount_cents", draft_fields, expense.amount_cents is None)
        and merged.amount_cents is not None
    ):
        expense.amount_cents = merged.amount_cents
        applied_fields.add("amount_cents")
    if _can_apply_ocr_field("merchant", draft_fields, not (expense.merchant or "").strip()) and merged.merchant:
        expense.merchant = merged.merchant
        applied_fields.add("merchant")
    if (
        _can_apply_ocr_field("expense_time", draft_fields, expense.expense_time is None)
        and merged.expense_time is not None
    ):
        expense.expense_time = ensure_utc(merged.expense_time)
        applied_fields.add("expense_time")
    if (
        _can_apply_ocr_field("category", draft_fields, normalize_category(expense.category) == "其他")
        and merged.category
    ):
        expense.category = normalize_category(merged.category)
        applied_fields.add("category")
    home = home_currency_code()
    if expense.amount_cents is not None and expense.original_currency_code == home:
        expense.original_amount_minor = expense.amount_cents
        expense.exchange_rate_to_cny = Decimal("1")
        expense.exchange_rate_date = default_rate_date(expense.expense_time)
        expense.exchange_rate_source = FX_SOURCE_BASE
        expense.home_currency_code = home
        expense.fx_status = FX_STATUS_READY
    if applied_fields:
        _write_ocr_draft_fields(expense, draft_fields.union(applied_fields))


def _can_apply_ocr_field(field: str, draft_fields: set[str], is_empty_or_default: bool) -> bool:
    return is_empty_or_default or field in draft_fields


def _legacy_pending_ocr_draft_fields(expense: Expense) -> set[str]:
    if expense.status != "pending":
        return set()
    if not (expense.raw_text or "").strip() or expense.confidence is None:
        return set()
    created_at = ensure_utc(expense.created_at)
    updated_at = ensure_utc(expense.updated_at)
    if created_at is None or updated_at is None:
        return set()
    if updated_at - created_at > LEGACY_AUTO_OCR_WINDOW:
        return set()

    fields: set[str] = set()
    if expense.amount_cents is not None:
        fields.add("amount_cents")
    if (expense.merchant or "").strip():
        fields.add("merchant")
    if normalize_category(expense.category) != "其他":
        fields.add("category")
    if expense.expense_time is not None:
        fields.add("expense_time")
    return fields


def _write_ocr_draft_fields(expense: Expense, fields: set[str]) -> None:
    normalized = sorted(field for field in fields if field in OCR_DRAFT_FIELDS)
    expense.ocr_draft_fields = json.dumps(normalized, ensure_ascii=False)


def _merge_result_with_text_parse(
    result: OcrResult,
    *,
    parsed_confidence: float | None,
    timezone_name: str | None = None,
) -> OcrResult:
    parsed = parse_receipt_text(result.raw_text, timezone_name=timezone_name)
    return OcrResult(
        raw_text=result.raw_text,
        confidence=_best_confidence(result.confidence, parsed_confidence, parsed.confidence),
        amount_cents=result.amount_cents if result.amount_cents is not None else parsed.amount_cents,
        merchant=result.merchant or parsed.merchant,
        expense_time=result.expense_time or parsed.expense_time,
        category=result.category or parsed.category,
    )


def _needs_fallback(expense: Expense) -> bool:
    confidence = expense.confidence or 0
    return (
        confidence < get_settings().ocr_min_confidence
        or expense.amount_cents is None
        or not (expense.merchant or "").strip()
        or expense.expense_time is None
    )


def _best_confidence(*values: float | None) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return max(0.0, min(1.0, max(present)))


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


def _result_from_llm_json(payload: dict[str, Any], timezone_name: str | None = None) -> OcrResult:
    raw_text = str(payload.get("raw_text") or "")
    confidence = _coerce_float(payload.get("confidence"))
    amount_cents = _coerce_int(payload.get("amount_cents"))
    merchant = _coerce_optional_text(payload.get("merchant"))
    expense_time = _coerce_datetime(payload.get("expense_time"), timezone_name=timezone_name)
    category = _coerce_optional_text(payload.get("category"))
    return OcrResult(
        raw_text=raw_text,
        confidence=confidence,
        amount_cents=amount_cents,
        merchant=merchant,
        expense_time=expense_time,
        category=category,
    )


def _coerce_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "null":
        return None
    return text


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


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
