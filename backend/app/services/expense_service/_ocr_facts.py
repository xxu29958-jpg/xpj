"""Bridge OCR extraction results into append-only learning facts."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BackgroundTask, Expense, LedgerLearningEvent, RuleApplicationChange
from app.services.background_task_handler_api import OCR_TASK_TYPES
from app.services.expense_accounting_time_service import refresh_legacy_expense_time
from app.services.learning_service import OcrFactDraft, record_ocr_fact
from app.services.ocr_service import OcrResult, ocr_fact_snapshot
from app.services.ocr_service._apply import (
    _apply_ocr_home_snapshot,
    _apply_ocr_result_to_expense,
    _expense_ocr_materialization_money_context,
    _parse_and_merge_for_expense,
)
from app.services.ocr_service._draft_fields import is_within_legacy_auto_ocr_window
from app.services.receipt_parse_common import ParsedReceipt

_HUMAN_LEARNING_EVENT_TYPES = frozenset({"edit", "manual_override", "accept", "reject"})


def _has_non_ocr_expense_changes(db: Session, expense: Expense) -> bool:
    has_rule_change = db.scalar(
        select(RuleApplicationChange.id)
        .where(
            RuleApplicationChange.tenant_id == expense.tenant_id,
            RuleApplicationChange.expense_id == expense.id,
        )
        .limit(1)
    )
    if has_rule_change is not None:
        return True
    has_human_learning = db.scalar(
        select(LedgerLearningEvent.id)
        .where(
            LedgerLearningEvent.tenant_id == expense.tenant_id,
            LedgerLearningEvent.subject_kind == "expense",
            LedgerLearningEvent.subject_id == expense.id,
            LedgerLearningEvent.event_type.in_(_HUMAN_LEARNING_EVENT_TYPES),
        )
        .limit(1)
    )
    return has_human_learning is not None


def _ocr_task_completed_version_step(task: BackgroundTask) -> int | None:
    try:
        payload = json.loads(task.input_payload_json or "{}")
        summary = json.loads(task.result_summary_json or "{}")
    except (TypeError, ValueError):
        return None
    expected_ver = payload.get("expected_row_version")
    result_ver = summary.get("row_version")
    outcome = summary.get("outcome")
    if (
        isinstance(expected_ver, int)
        and isinstance(result_ver, int)
        and result_ver == expected_ver + 1
        and outcome in {"updated", "no_result"}
    ):
        return expected_ver
    return None


def has_proven_ocr_only_version_chain(
    db: Session,
    expense: Expense,
    pre_claim_row_version: int,
) -> bool:
    """True when DB records prove every version bump up to ``pre_claim_row_version`` was OCR-only."""
    if (expense.source or "") == "手动记账" or expense.id is None or pre_claim_row_version < 1:
        return False
    if _has_non_ocr_expense_changes(db, expense):
        return False
    if pre_claim_row_version == 1:
        return True
    tasks = db.scalars(
        select(BackgroundTask).where(
            BackgroundTask.tenant_id == expense.tenant_id,
            BackgroundTask.source_expense_id == expense.id,
            BackgroundTask.task_type.in_(OCR_TASK_TYPES),
            BackgroundTask.status == "completed",
            BackgroundTask.input_payload_json.is_not(None),
            BackgroundTask.result_summary_json.is_not(None),
        )
    )
    steps = {
        step
        for task in tasks
        if (step := _ocr_task_completed_version_step(task)) is not None
    }
    return all(version in steps for version in range(1, pre_claim_row_version))


def resolve_legacy_ocr_eligibility(
    db: Session,
    expense: Expense,
    pre_claim_row_version: int,
) -> tuple[bool, bool]:
    """Return ``(allow_legacy_ocr_only, allow_legacy_untouched)`` for pre-upgrade compatibility."""
    if (expense.source or "") == "手动记账":
        return False, False
    ocr_only_chain = (
        pre_claim_row_version > 1
        and has_proven_ocr_only_version_chain(db, expense, pre_claim_row_version)
    )
    if expense.ocr_draft_fields is None:
        if ocr_only_chain:
            return True, True
        if pre_claim_row_version <= 1 and (
            expense.confidence is None or is_within_legacy_auto_ocr_window(expense)
        ):
            return False, True
        return False, False
    if ocr_only_chain:
        return True, True
    if (
        pre_claim_row_version <= 1
        and (expense.source or "").startswith("通知草稿:")
        and has_proven_ocr_only_version_chain(db, expense, 1)
    ):
        return False, True
    return False, False


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
    pre_claim_row_version: int | None = None,
) -> OcrResult | None:
    if expense.status != "pending":
        return None
    parsed, _, _ = _parse_and_merge_for_expense(expense, result, timezone_name=timezone_name)
    if parsed.events:
        return _apply_source_events(db, expense=expense, result=result, parsed=parsed,
            provider_name=provider_name, ocr_model=ocr_model, timezone_name=timezone_name,
            apply_to_draft=apply_to_draft, record_source_fact=record_source_fact,
            pre_claim_row_version=pre_claim_row_version)
    if not apply_to_draft:
        if record_source_fact:
            append_ocr_fact(db, expense=expense, result=result, provider_name=provider_name,
                ocr_model=ocr_model, timezone_name=timezone_name)
        return None
    _apply_one_result(db, expense=expense, result=result, provider_name=provider_name,
        ocr_model=ocr_model, timezone_name=timezone_name, pre_claim_row_version=pre_claim_row_version)
    return result


def _apply_source_events(
    db: Session,
    *,
    expense: Expense,
    result: OcrResult,
    parsed: ParsedReceipt,
    provider_name: str,
    ocr_model: str | None,
    timezone_name: str | None,
    apply_to_draft: bool,
    record_source_fact: bool,
    pre_claim_row_version: int | None = None,
) -> OcrResult | None:
    from app.services.duplicate_service import mark_duplicate_status
    from app.services.expense_service._helpers import _replace_ocr_draft_items_from_text
    from app.services.expense_source_candidates import stage_source_event_drafts

    eff_ver = expense.row_version if pre_claim_row_version is None else pre_claim_row_version
    allow_ocr_only, allow_untouched = resolve_legacy_ocr_eligibility(db, expense, eff_ver or 1)
    current = None
    for event in stage_source_event_drafts(db, expense=expense, result=result, parsed=parsed,
            provider_name=provider_name, ocr_model=ocr_model, use_source_draft=apply_to_draft,
            effective_row_version=eff_ver, allow_legacy_ocr_only=allow_ocr_only,
            allow_legacy_untouched=allow_untouched):
        event_pre_claim = pre_claim_row_version if event.expense.id == expense.id else 1
        _apply_one_result(db, expense=event.expense, result=event.result, provider_name=provider_name,
            ocr_model=ocr_model, timezone_name=timezone_name, pre_claim_row_version=event_pre_claim)
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
        provider_name: str, ocr_model: str | None, timezone_name: str | None,
        pre_claim_row_version: int | None = None) -> None:
    # Runtime import keeps the persistent bridge connected to the current split
    # owner without making the pure OCR module depend on SQLAlchemy services.
    from app.services.expense_split_service import current_expense_split_total_amount

    eff_ver = expense.row_version if pre_claim_row_version is None else pre_claim_row_version
    allow_ocr_only, allow_untouched = resolve_legacy_ocr_eligibility(db, expense, eff_ver or 1)
    _apply_ocr_result_to_expense(
        expense,
        result,
        timezone_name=timezone_name,
        allow_session_bound=True,
        split_allocation_floor_cents=current_expense_split_total_amount(
            db,
            expense=expense,
        ),
        effective_row_version=eff_ver,
        allow_legacy_ocr_only=allow_ocr_only,
        allow_legacy_untouched=allow_untouched,
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
