"""Create-side flows: upload-driven pending, manual entry, notification draft.

``create_pending_expense`` is the only entry point from the upload route;
``enrich_pending_expense`` is its background follow-up (so the HTTP response
returns before OCR/thumbnail/classification run). The manual and notification
flows are tenant-facing direct-create paths that bypass uploads entirely.
"""

from __future__ import annotations

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Expense
from app.schemas import ExpenseManualCreateRequest, NotificationDraftCreateRequest
from app.services.classify_service import classify_expense
from app.services.duplicate_service import mark_duplicate_status
from app.services.exchange_rate_service import apply_currency_payload
from app.services.expense_service._helpers import (
    NOTIFICATION_DRAFT_SOURCE_LABELS,
    _begin_immediate_write_if_sqlite,
    _clean_category,
    _clean_notification_source,
    _clean_optional_text,
    _clean_text,
    _expense_has_pending_fx,
    _notification_draft_fields,
    _notification_draft_key,
    _replace_ocr_draft_items_from_text,
    _try_generate_thumbnail,
)
from app.services.expense_service._ocr_facts import apply_ocr_result_and_append_fact
from app.services.file_service import SavedUpload, delete_relative_upload
from app.services.ocr_service import (
    collect_auto_ocr_extractions,
)
from app.services.tag_service import normalize_tags, sync_expense_tags
from app.services.time_service import ensure_utc, now_utc

logger = logging.getLogger(__name__)


__all__ = [
    "create_manual_expense",
    "create_notification_draft",
    "create_pending_expense",
    "enrich_pending_expense",
]


def _apply_pending_enrichment(db: Session, expense: Expense) -> None:
    if not expense.thumbnail_path:
        expense.thumbnail_path = _try_generate_thumbnail(
            expense.image_path, expense.tenant_id
        )
    for extraction in collect_auto_ocr_extractions(expense):
        apply_ocr_result_and_append_fact(
            db,
            expense=expense,
            result=extraction.result,
            provider_name=extraction.provider_name,
            ocr_model=extraction.ocr_model,
        )
        _replace_ocr_draft_items_from_text(db, expense, extraction.result.raw_text)
    if expense.category == "其他":
        classify_expense(db, expense)
    if (
        expense.amount_cents is not None
        or expense.merchant
        or expense.expense_time is not None
    ):
        mark_duplicate_status(db, expense)


def create_pending_expense(
    db: Session,
    saved_file: SavedUpload,
    tenant_id: str,
    *,
    source: str = "iPhone截图",
    run_enrichment: bool = True,
) -> Expense:
    now = now_utc()
    thumbnail_path = (
        _try_generate_thumbnail(saved_file.relative_path, tenant_id)
        if run_enrichment
        else None
    )
    expense = Expense(
        tenant_id=tenant_id,
        amount_cents=None,
        merchant=None,
        category="其他",
        note="",
        source=source,
        image_path=saved_file.relative_path,
        thumbnail_path=thumbnail_path,
        image_hash=saved_file.image_hash,
        raw_text="",
        confidence=None,
        status="pending",
        created_at=now,
        updated_at=now,
    )
    try:
        db.add(expense)
        db.flush()
        mark_duplicate_status(db, expense)
        if run_enrichment:
            _apply_pending_enrichment(db, expense)
        expense.updated_at = now_utc()
        db.commit()
        db.refresh(expense)
        return expense
    except Exception:
        db.rollback()
        delete_relative_upload(thumbnail_path)
        delete_relative_upload(saved_file.relative_path)
        raise


def enrich_pending_expense(
    expense_id: int, tenant_id: str, timezone_name: str | None = None
) -> None:
    """Fill OCR/category draft fields after the upload response has been sent."""
    from app.database import SessionLocal

    with SessionLocal() as db:
        expense = db.scalar(
            ledger_scoped_select(Expense, tenant_id).where(Expense.id == expense_id)
        )
        if expense is None or expense.status != "pending":
            return

        ocr_extractions = collect_auto_ocr_extractions(
            expense, timezone_name=timezone_name
        )

    with SessionLocal() as db:
        try:
            _begin_immediate_write_if_sqlite(db)
            expense = db.scalar(
                ledger_scoped_select(Expense, tenant_id).where(Expense.id == expense_id)
            )
            if expense is None or expense.status != "pending":
                return
            if not expense.thumbnail_path:
                expense.thumbnail_path = _try_generate_thumbnail(
                    expense.image_path, expense.tenant_id
                )
            for extraction in ocr_extractions:
                apply_ocr_result_and_append_fact(
                    db,
                    expense=expense,
                    result=extraction.result,
                    provider_name=extraction.provider_name,
                    ocr_model=extraction.ocr_model,
                    timezone_name=timezone_name,
                )
                _replace_ocr_draft_items_from_text(
                    db, expense, extraction.result.raw_text, timezone_name=timezone_name
                )
            if expense.category == "其他":
                classify_expense(db, expense)
            if (
                expense.amount_cents is not None
                or expense.merchant
                or expense.expense_time is not None
            ):
                mark_duplicate_status(db, expense)
            expense.updated_at = now_utc()
            db.commit()
        except Exception:
            # Auto-enrichment runs after the upload response has already
            # been returned to the client. We intentionally don't propagate
            # — the row is still in `pending` and the user can retry OCR
            # manually. Record the failure so it isn't invisible.
            from app.services.expense_service._helpers import _record_background_failure
            _record_background_failure("auto_enrich")
            logger.exception(
                "auto enrichment failed for expense_id=%s tenant_id=%s",
                expense_id,
                tenant_id,
            )
            db.rollback()


def create_manual_expense(
    db: Session, payload: ExpenseManualCreateRequest, tenant_id: str
) -> Expense:
    now = now_utc()
    expense = Expense(
        tenant_id=tenant_id,
        amount_cents=payload.amount_cents,
        merchant=_clean_optional_text(payload.merchant),
        category=_clean_category(payload.category),
        note=_clean_text(payload.note),
        source="手动记账",
        image_path=None,
        thumbnail_path=None,
        image_hash=None,
        raw_text="",
        confidence=None,
        status="confirmed",
        expense_time=ensure_utc(payload.spent_at or payload.expense_time) or now,
        created_at=now,
        updated_at=now,
        confirmed_at=now,
        tags=normalize_tags(payload.tags),
        value_score=payload.value_score,
        regret_score=payload.regret_score,
    )
    apply_currency_payload(
        db,
        tenant_id=tenant_id,
        expense=expense,
        payload=payload,
        amount_was_explicit=payload.amount_cents is not None,
    )
    if expense.amount_cents is None and expense.original_amount_minor is None:
        raise AppError("amount_required", status_code=400)
    if _expense_has_pending_fx(expense):
        expense.status = "pending"
        expense.confirmed_at = None
    if expense.category == "其他":
        classify_expense(db, expense)
    db.add(expense)
    db.flush()
    sync_expense_tags(db, expense)
    mark_duplicate_status(db, expense)
    db.commit()
    db.refresh(expense)
    return expense


def create_notification_draft(
    db: Session,
    payload: NotificationDraftCreateRequest,
    tenant_id: str,
) -> Expense:
    now = now_utc()
    source = _clean_notification_source(payload.source)
    idempotency_key = _notification_draft_key(
        source=source,
        merchant=payload.merchant,
        amount_cents=payload.amount_cents,
        original_currency=payload.original_currency or payload.original_currency_code,
        original_amount=payload.original_amount or payload.original_amount_minor,
        expense_time=payload.spent_at or payload.expense_time,
        now=now,
    )
    existing = db.scalar(
        ledger_scoped_select(Expense, tenant_id).where(
            Expense.draft_idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        return existing

    source_label = NOTIFICATION_DRAFT_SOURCE_LABELS[source]
    expense = Expense(
        tenant_id=tenant_id,
        amount_cents=payload.amount_cents,
        merchant=_clean_optional_text(payload.merchant),
        category=_clean_category(payload.category),
        note="",
        source=f"通知草稿:{source_label}",
        image_path=None,
        thumbnail_path=None,
        image_hash=None,
        raw_text="",
        confidence=None,
        ocr_draft_fields=_notification_draft_fields(payload),
        draft_idempotency_key=idempotency_key,
        status="pending",
        expense_time=ensure_utc(payload.spent_at or payload.expense_time) if (payload.spent_at or payload.expense_time) else None,
        created_at=now,
        updated_at=now,
    )
    apply_currency_payload(
        db,
        tenant_id=tenant_id,
        expense=expense,
        payload=payload,
        amount_was_explicit=payload.amount_cents is not None,
    )
    db.add(expense)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            ledger_scoped_select(Expense, tenant_id).where(
                Expense.draft_idempotency_key == idempotency_key
            )
        )
        if existing is not None:
            return existing
        raise
    if expense.category == "其他":
        classify_expense(db, expense)
    if expense.amount_cents is not None or expense.merchant or expense.expense_time is not None:
        mark_duplicate_status(db, expense)
    expense.updated_at = now_utc()
    db.commit()
    db.refresh(expense)
    return expense
