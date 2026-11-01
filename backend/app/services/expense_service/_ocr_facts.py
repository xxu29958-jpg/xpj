"""Bridge OCR extraction results into append-only learning facts."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models import Expense
from app.services.expense_accounting_time_service import refresh_legacy_expense_time
from app.services.learning_service import OcrFactDraft, record_ocr_fact
from app.services.ocr_service import OcrResult, ocr_fact_snapshot
from app.services.ocr_service._apply import (
    _apply_ocr_home_snapshot,
    _apply_ocr_result_to_expense,
    _expense_ocr_materialization_money_context,
    _parse_and_merge_for_expense,
)


def apply_ocr_result_and_append_fact(
    db: Session,
    *,
    expense: Expense,
    result: OcrResult,
    provider_name: str,
    ocr_model: str | None = None,
    timezone_name: str | None = None,
    apply_to_draft: bool = True,
    record_source_fact: bool = True,
) -> OcrResult | None:
    if expense.status != "pending":
        return None
    parsed, _, _ = _parse_and_merge_for_expense(expense, result, timezone_name=timezone_name)
    if parsed.events:
        return _apply_source_events(db, expense=expense, result=result, parsed=parsed,
            provider_name=provider_name, ocr_model=ocr_model, timezone_name=timezone_name,
            apply_to_draft=apply_to_draft, record_source_fact=record_source_fact)
    if not apply_to_draft:
        if record_source_fact:
            append_ocr_fact(db, expense=expense, result=result, provider_name=provider_name,
                ocr_model=ocr_model, timezone_name=timezone_name)
        return None
    _apply_one_result(db, expense=expense, result=result, provider_name=provider_name,
        ocr_model=ocr_model, timezone_name=timezone_name)
    return result


def _apply_source_events(db, *, expense, result, parsed, provider_name, ocr_model, timezone_name, apply_to_draft, record_source_fact):
    from app.services.duplicate_service import mark_duplicate_status
    from app.services.expense_service._helpers import _replace_ocr_draft_items_from_text
    from app.services.expense_source_candidates import stage_source_event_drafts

    current = None
    for event in stage_source_event_drafts(db, expense=expense, result=result, parsed=parsed,
            provider_name=provider_name, ocr_model=ocr_model, use_source_draft=apply_to_draft):
        _apply_one_result(db, expense=event.expense, result=event.result, provider_name=provider_name,
            ocr_model=ocr_model, timezone_name=timezone_name)
        if event.expense.id != expense.id:
            _replace_ocr_draft_items_from_text(db, event.expense, event.result.raw_text, timezone_name=timezone_name)
        mark_duplicate_status(db, event.expense)
        if event.expense.id == expense.id:
            current = event.result
    if current is None and record_source_fact:
        append_ocr_fact(db, expense=expense, result=result, provider_name=provider_name,
            ocr_model=ocr_model, timezone_name=timezone_name)
    return current


def _apply_one_result(db: Session, *, expense: Expense, result: OcrResult,
        provider_name: str, ocr_model: str | None, timezone_name: str | None) -> None:
    # Runtime import keeps the persistent bridge connected to the current split
    # owner without making the pure OCR module depend on SQLAlchemy services.
    from app.services.expense_split_service import current_expense_split_total_amount

    _apply_ocr_result_to_expense(
        expense,
        result,
        timezone_name=timezone_name,
        allow_session_bound=True,
        split_allocation_floor_cents=current_expense_split_total_amount(
            db,
            expense=expense,
        ),
    )
    refresh_legacy_expense_time(db, expense)
    _apply_ocr_home_snapshot(expense, _expense_ocr_materialization_money_context(expense))
    append_ocr_fact(
        db,
        expense=expense,
        result=result,
        provider_name=provider_name,
        ocr_model=ocr_model,
        timezone_name=timezone_name,
    )


def append_ocr_fact(
    db: Session,
    *,
    expense: Expense,
    result: OcrResult,
    provider_name: str,
    ocr_model: str | None = None,
    timezone_name: str | None = None,
) -> None:
    snapshot = ocr_fact_snapshot(
        result,
        expense=expense,
        timezone_name=timezone_name,
    )
    record_ocr_fact(
        db,
        OcrFactDraft(
            tenant_id=expense.tenant_id,
            expense_id=expense.id,
            ocr_provider=provider_name,
            ocr_model=ocr_model,
            raw_text=snapshot.raw_text,
            evidence_json=(json.dumps(snapshot.evidence, ensure_ascii=False, allow_nan=False)
                           if snapshot.evidence is not None else None),
            parsed_amount_cents=snapshot.parsed_amount_cents,
            parsed_merchant=snapshot.parsed_merchant,
            parsed_category=snapshot.parsed_category,
            parsed_expense_time=snapshot.parsed_expense_time,
            parse_confidence=snapshot.parse_confidence,
        ),
    )
