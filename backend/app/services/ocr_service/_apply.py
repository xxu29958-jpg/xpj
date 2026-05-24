"""High-level orchestration: run providers, apply results onto an Expense."""

from __future__ import annotations

import logging
from decimal import Decimal

from app.config import get_settings
from app.fx_constants import FX_SOURCE_BASE, FX_STATUS_READY
from app.models import Expense
from app.services.category_service import normalize_category
from app.services.exchange_rate_service import default_rate_date, home_currency_code
from app.services.ocr_service._draft_fields import _write_ocr_draft_fields, ocr_draft_fields
from app.services.ocr_service._merge import _best_confidence, _merge_result_with_text_parse
from app.services.ocr_service._models import (
    OcrExtraction,
    OcrFactSnapshot,
    OcrProvider,
    OcrResult,
)
from app.services.ocr_service._providers import get_ocr_provider
from app.services.receipt_parse_service import parse_receipt_text
from app.services.time_service import ensure_utc

logger = logging.getLogger(__name__)


def extract_ocr_result(
    expense: Expense,
    provider: OcrProvider | None = None,
    timezone_name: str | None = None,
) -> OcrResult:
    active_provider = provider or get_ocr_provider()
    return active_provider.extract(expense, timezone_name=timezone_name)


def retry_ocr(expense: Expense, provider: OcrProvider | None = None, timezone_name: str | None = None) -> Expense:
    result = extract_ocr_result(expense, provider=provider, timezone_name=timezone_name)
    apply_ocr_result(expense, result, timezone_name=timezone_name)
    return expense


def collect_auto_ocr_extractions(
    expense: Expense, timezone_name: str | None = None
) -> list[OcrExtraction]:
    """Run configured OCR providers and return draft results with provenance."""
    settings = get_settings()
    if not settings.ocr_auto_run:
        return []
    primary_name = _normalise_provider_name(settings.ocr_provider)
    if primary_name == "empty":
        return []

    try:
        primary_result = get_ocr_provider(primary_name).extract(
            expense, timezone_name=timezone_name
        )
        results = [
            OcrExtraction(
                provider_name=primary_name,
                ocr_model=_provider_model(primary_name),
                result=primary_result,
            )
        ]

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
        fallback_name = _normalise_provider_name(settings.ocr_fallback_provider)
        if (
            _needs_fallback(draft)
            and fallback_name not in {"", "empty", primary_name}
        ):
            fallback_result = get_ocr_provider(fallback_name).extract(
                expense, timezone_name=timezone_name
            )
            results.append(
                OcrExtraction(
                    provider_name=fallback_name,
                    ocr_model=_provider_model(fallback_name),
                    result=fallback_result,
                )
            )
        return results
    except Exception:
        # Upload must stay reliable. Manual retry exposes provider errors to the user.
        logger.exception("auto OCR failed for expense=%s ledger=%s", expense.id, expense.tenant_id)
        return []


def collect_auto_ocr_results(expense: Expense, timezone_name: str | None = None) -> list[OcrResult]:
    """Backward-compatible result-only wrapper for tests and old callers."""

    return [
        extraction.result
        for extraction in collect_auto_ocr_extractions(
            expense, timezone_name=timezone_name
        )
    ]


def run_auto_ocr(expense: Expense, timezone_name: str | None = None) -> None:
    for extraction in collect_auto_ocr_extractions(expense, timezone_name=timezone_name):
        apply_ocr_result(expense, extraction.result, timezone_name=timezone_name)


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


def _needs_fallback(expense: Expense) -> bool:
    confidence = expense.confidence or 0
    return (
        confidence < get_settings().ocr_min_confidence
        or expense.amount_cents is None
        or not (expense.merchant or "").strip()
        or expense.expense_time is None
    )


def ocr_fact_snapshot(
    result: OcrResult, timezone_name: str | None = None
) -> OcrFactSnapshot:
    """Build the append-only fact snapshot from the extraction itself.

    This intentionally does not inspect the mutable ``Expense`` row:
    OCR facts describe what the OCR/text pipeline produced, even if a
    field is not allowed to overwrite a user-edited draft value.
    """

    parsed = parse_receipt_text(result.raw_text, timezone_name=timezone_name)
    merged = _merge_result_with_text_parse(
        result, parsed_confidence=parsed.confidence, timezone_name=timezone_name
    )
    return OcrFactSnapshot(
        raw_text=merged.raw_text,
        parsed_amount_cents=merged.amount_cents,
        parsed_merchant=merged.merchant,
        parsed_category=normalize_category(merged.category) if merged.category else None,
        parsed_expense_time=ensure_utc(merged.expense_time),
        parse_confidence=_best_confidence(
            merged.confidence, parsed.confidence, None
        ),
    )


def _normalise_provider_name(provider_name: str | None) -> str:
    clean = (provider_name or "").strip().lower()
    if clean in {"rapid_ocr"}:
        return "rapidocr"
    if clean in {"local_vlm", "vlm"}:
        return "local_llm"
    if clean:
        return clean
    return "empty"


def _provider_model(provider_name: str) -> str | None:
    if provider_name == "local_llm":
        return get_settings().local_llm_model or None
    if provider_name == "rapidocr":
        return "rapidocr"
    return None
