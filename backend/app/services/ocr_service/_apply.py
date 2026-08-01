"""High-level orchestration: run providers, apply results onto an Expense."""

from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import inspect as sa_inspect

from app.config import get_settings
from app.errors import AppError
from app.fx_constants import FX_SOURCE_BASE, FX_STATUS_READY
from app.models import Expense
from app.money_contract import (
    MoneySign,
    ensure_optional_money_minor,
)
from app.services.category_service import normalize_category
from app.services.currency_common import minor_unit_digits
from app.services.exchange_rate_service import default_rate_date
from app.services.ocr_service._draft_fields import _write_ocr_draft_fields, ocr_draft_fields
from app.services.ocr_service._merge import _best_confidence, _safe_category
from app.services.ocr_service._models import (
    OcrExtraction,
    OcrFactSnapshot,
    OcrProvider,
    OcrResult,
)
from app.services.ocr_service._providers import get_ocr_provider
from app.services.receipt_parse_common import ParsedReceipt
from app.services.receipt_parse_service import parse_receipt_text
from app.services.time_service import ensure_utc

logger = logging.getLogger(__name__)

_AUTO_OCR_FAILURES = (AppError, ImportError, OSError, RuntimeError, ValueError, TypeError)


class OcrApplyContractError(RuntimeError):
    """OCR draft application would break the required fact-and-mirror pairing."""


def _explicit_money_context(
    currency_code: str | None,
) -> tuple[str, int] | None:
    code = (currency_code or "").strip().upper()
    if not code:
        return None
    try:
        return code, minor_unit_digits(code)
    except AppError:
        return None


def _expense_ocr_source_money_context(
    expense: Expense,
) -> tuple[str, int] | None:
    """Return the frozen original-currency context for receipt text."""

    return _explicit_money_context(expense.original_currency_code)


def _expense_ocr_materialization_money_context(
    expense: Expense,
) -> tuple[str, int] | None:
    """Return the context that may directly update home minor units.

    OCR supplies no authoritative FX rate. A parsed original-currency amount
    is therefore materializable only when the frozen original and home
    currencies are both explicit, supported, and identical.
    """

    source_context = _expense_ocr_source_money_context(expense)
    home_context = _explicit_money_context(expense.home_currency_code)
    if source_context is None or home_context is None:
        return None
    return home_context if source_context == home_context else None


def _validated_ocr_amount(value: object | None, *, label: str) -> int | None:
    try:
        return ensure_optional_money_minor(
            value,
            sign=MoneySign.POSITIVE,
            label=label,
        )
    except (AppError, TypeError, ValueError):
        return None


def _merge_result_with_explicit_parse(
    result: OcrResult,
    parsed: ParsedReceipt,
) -> OcrResult:
    """Merge only money corroborated under one explicit currency exponent."""

    provider_amount = _validated_ocr_amount(
        result.amount_cents,
        label="ocr.provider_amount_cents",
    )
    parsed_amount = _validated_ocr_amount(
        parsed.amount_cents,
        label="ocr.parsed_amount_cents",
    )
    if provider_amount is None:
        merged_amount = parsed_amount
    elif parsed_amount is not None and provider_amount == parsed_amount:
        merged_amount = provider_amount
    else:
        merged_amount = None
    return OcrResult(
        raw_text=result.raw_text,
        confidence=_best_confidence(result.confidence, parsed.confidence),
        amount_cents=merged_amount,
        merchant=result.merchant or parsed.merchant,
        expense_time=result.expense_time or parsed.expense_time,
        category=_safe_category(result.category) or _safe_category(parsed.category),
    )


def _parse_and_merge_for_expense(
    expense: Expense,
    result: OcrResult,
    *,
    timezone_name: str | None,
) -> tuple[ParsedReceipt, OcrResult, tuple[str, int] | None]:
    source_context = _expense_ocr_source_money_context(expense)
    currency_code = source_context[0] if source_context is not None else None
    minor_unit_exponent = source_context[1] if source_context is not None else None
    parsed = parse_receipt_text(
        result.raw_text,
        timezone_name=timezone_name,
        currency_code=currency_code,
        minor_unit_exponent=minor_unit_exponent,
    )
    return (
        parsed,
        _merge_result_with_explicit_parse(result, parsed),
        _expense_ocr_materialization_money_context(expense),
    )


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
            home_currency_code=expense.home_currency_code,
            original_currency_code=expense.original_currency_code,
            original_amount_minor=expense.original_amount_minor,
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
            if _fallback_confidence_is_not_worse(
                primary_result,
                fallback_result,
                expense=expense,
                timezone_name=timezone_name,
            ):
                results.append(
                    OcrExtraction(
                        provider_name=fallback_name,
                        ocr_model=_provider_model(fallback_name),
                        result=fallback_result,
                    )
                )
        return results
    except _AUTO_OCR_FAILURES:
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
    """Apply OCR to a transient Expense draft.

    Persistent expense rows must use
    ``expense_service._ocr_facts.apply_ocr_result_and_append_fact`` so
    the denormalized ``expenses.raw_text``/``confidence`` mirror cannot
    be updated without an append-only ``ocr_facts`` row in the same unit
    of work.
    """

    _apply_ocr_result_to_expense(
        expense,
        result,
        timezone_name=timezone_name,
        allow_session_bound=False,
    )


def _apply_ocr_candidate_fields(
    expense: Expense,
    merged: OcrResult,
    *,
    merged_amount: int | None,
    materialization_context: tuple[str, int] | None,
    draft_fields: set[str],
) -> set[str]:
    applied_fields: set[str] = set()
    if (
        materialization_context is not None
        and _can_apply_ocr_field(
            "amount_cents",
            draft_fields,
            expense.amount_cents is None,
        )
        and merged_amount is not None
    ):
        expense.amount_cents = merged_amount
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
    return applied_fields


def _apply_ocr_home_snapshot(
    expense: Expense,
    materialization_context: tuple[str, int] | None,
) -> None:
    frozen_home = materialization_context[0] if materialization_context is not None else None
    if expense.amount_cents is None or frozen_home is None:
        return
    expense.original_amount_minor = expense.amount_cents
    expense.exchange_rate_to_cny = Decimal("1")
    expense.exchange_rate_date = default_rate_date(expense.expense_time)
    expense.exchange_rate_source = FX_SOURCE_BASE
    expense.home_currency_code = frozen_home
    expense.fx_status = FX_STATUS_READY


def _apply_ocr_result_to_expense(
    expense: Expense,
    result: OcrResult,
    timezone_name: str | None = None,
    *,
    allow_session_bound: bool,
) -> None:
    if expense.status != "pending":
        return
    if not allow_session_bound:
        _ensure_ocr_apply_is_not_session_bound(expense)

    parsed, merged, materialization_context = _parse_and_merge_for_expense(
        expense,
        result,
        timezone_name=timezone_name,
    )
    merged_amount = _validated_ocr_amount(
        merged.amount_cents,
        label="ocr.merged_amount_cents",
    )
    draft_fields = ocr_draft_fields(expense)

    # v1.2 OCR single-source migration: ``ocr_facts`` is the source
    # of truth for OCR text. The API response assembler now reads
    # raw_text from facts; this column write remains a compatibility
    # mirror only. No business-logic reader consults the column
    # anymore (step 4 dropped the last one).
    #
    # Mirror is **only** updated when this OCR pass produced text.
    # An empty ``merged.raw_text`` means the provider couldn't read
    # anything this round (e.g. ``EmptyOcrProvider`` on an unconfigured
    # system, or a provider error that surfaced as a hollow result).
    # In that case the previous mirror value is the better answer for
    # compatibility storage than ``""`` — ``read_ocr_text`` walks back
    # to the latest non-empty fact and the response uses that canonical
    # logical "most recent meaningful OCR".
    if merged.raw_text:
        expense.raw_text = merged.raw_text
    expense.confidence = _best_confidence(merged.confidence, parsed.confidence, expense.confidence)
    applied_fields = _apply_ocr_candidate_fields(
        expense,
        merged,
        merged_amount=merged_amount,
        materialization_context=materialization_context,
        draft_fields=draft_fields,
    )
    _apply_ocr_home_snapshot(expense, materialization_context)
    if applied_fields:
        _write_ocr_draft_fields(expense, draft_fields.union(applied_fields))


def _ensure_ocr_apply_is_not_session_bound(expense: Expense) -> None:
    state = sa_inspect(expense, raiseerr=False)
    if state is not None and (state.persistent or state.pending):
        raise OcrApplyContractError(
            "apply_ocr_result cannot mutate a Session-bound Expense; "
            "use apply_ocr_result_and_append_fact so OCR facts stay paired "
            "with the response mirror."
        )


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


def _fallback_confidence_is_not_worse(
    primary_result: OcrResult,
    fallback_result: OcrResult,
    *,
    expense: Expense,
    timezone_name: str | None = None,
) -> bool:
    return (
        _effective_ocr_confidence(
            fallback_result,
            expense=expense,
            timezone_name=timezone_name,
        )
        >= _effective_ocr_confidence(
            primary_result,
            expense=expense,
            timezone_name=timezone_name,
        )
    )


def _effective_ocr_confidence(
    result: OcrResult,
    *,
    expense: Expense,
    timezone_name: str | None = None,
) -> float:
    parsed, merged, _materialization_context = _parse_and_merge_for_expense(
        expense,
        result,
        timezone_name=timezone_name,
    )
    return _best_confidence(merged.confidence, parsed.confidence, result.confidence) or 0.0


def ocr_fact_snapshot(
    result: OcrResult,
    *,
    expense: Expense,
    timezone_name: str | None = None,
) -> OcrFactSnapshot:
    """Build the append-only fact snapshot from the extraction itself.

    The Expense contributes only its frozen money context. OCR facts still
    describe what the extraction produced, even if a field is not allowed to
    overwrite a user-edited draft value.
    """

    parsed, merged, materialization_context = _parse_and_merge_for_expense(
        expense,
        result,
        timezone_name=timezone_name,
    )
    parsed_amount = (
        _validated_ocr_amount(
            merged.amount_cents,
            label="ocr_fact.parsed_amount_cents",
        )
        if materialization_context is not None
        else None
    )
    return OcrFactSnapshot(
        raw_text=merged.raw_text,
        parsed_amount_cents=parsed_amount,
        parsed_merchant=merged.merchant,
        parsed_category=normalize_category(merged.category) if merged.category else None,
        parsed_expense_time=ensure_utc(merged.expense_time),
        parse_confidence=_best_confidence(
            merged.confidence, parsed.confidence, None
        ),
    )


def _normalise_provider_name(provider_name: str | None) -> str:
    clean = (provider_name or "").strip().lower()
    if clean in {"empty", "mock", "rapidocr", "local_llm"}:
        return clean
    if clean in {"rapid_ocr"}:
        return "rapidocr"
    if clean in {"local_vlm", "vlm"}:
        return "local_llm"
    return "empty"


def _provider_model(provider_name: str) -> str | None:
    if provider_name == "local_llm":
        return get_settings().local_llm_model or None
    if provider_name == "rapidocr":
        return "rapidocr"
    return None
