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
from app.services.expense_query import local_ref_storage_key, resolve_expense
from app.services.expense_service._helpers import (
    NOTIFICATION_DRAFT_SOURCE_LABELS,
    NOTIFICATION_DRAFT_SOURCE_PREFIX,
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
from app.services.idempotency import fingerprint_request
from app.services.ocr_service import (
    collect_auto_ocr_extractions,
)
from app.services.optimistic_concurrency import bump_row_version
from app.services.tag_service import normalize_tags, sync_expense_tags
from app.services.time_service import ensure_utc, now_utc
from app.tenants import AuthContext

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
        image_perceptual_hash=saved_file.image_perceptual_hash,
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
        expense = resolve_expense(db, tenant_id, expense_id)
        if expense is None or expense.status != "pending":
            return

        ocr_extractions = collect_auto_ocr_extractions(
            expense, timezone_name=timezone_name
        )

    generated_thumbnail_path: str | None = None
    with SessionLocal() as db:
        try:
            # PG-only (债 #1): the SQLite-only BEGIN IMMEDIATE whole-DB lock the
            # prior code took here is gone. We deliberately do NOT replace it with
            # a parent-row FOR UPDATE — that lock would be held across the slow
            # thumbnail I/O below (a lock-during-I/O anti-pattern), and prod (PG)
            # already ran this background enrichment with no lock at all (the old
            # shim was SQLite-only). Serializing concurrent same-expense
            # enrichment without holding a row lock over the I/O is deferred (low
            # value: single background worker, rare).
            expense = resolve_expense(db, tenant_id, expense_id)
            if expense is None or expense.status != "pending":
                return
            if not expense.thumbnail_path:
                generated_thumbnail_path = _try_generate_thumbnail(
                    expense.image_path, expense.tenant_id
                )
                expense.thumbnail_path = generated_thumbnail_path
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
            bump_row_version(expense)
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
            delete_relative_upload(generated_thumbnail_path)


def _manual_request_fingerprint(payload: ExpenseManualCreateRequest) -> str:
    """sha256 of the user-supplied manual-create body (issue #65 slice 1).

    Computed from the REQUEST as sent — never from the stored row — so the server's
    own mutations (auto-classify of ``category``, the ``expense_time`` → ``now``
    default, FX rate-derived ``amount_cents``) can't make a faithful replay look like
    a different request. ``client_ref`` is excluded: it IS the key, not part of the
    intent it guards.
    """
    body = payload.model_dump(mode="json", exclude_unset=True, exclude={"client_ref"})
    return fingerprint_request(
        operation="create_manual_expense",
        target_id=None,
        body=body,
        expected_row_version=None,
    )


def _find_manual_expense_by_key(
    db: Session, tenant_id: str, key: str
) -> Expense | None:
    return db.scalar(
        ledger_scoped_select(Expense, tenant_id).where(
            Expense.draft_idempotency_key == key
        )
    )


def _resolve_existing_manual_create(existing: Expense, fingerprint: str) -> Expense:
    """A row already owns this ``(device_id, client_ref)`` key: idempotent HIT iff the
    request fingerprint matches, else the ref was reused for a different expense."""
    if existing.draft_request_fingerprint != fingerprint:
        raise AppError("idempotency_key_reused", status_code=422)
    return existing


def _insert_manual_expense(
    db: Session,
    payload: ExpenseManualCreateRequest,
    tenant_id: str,
    *,
    draft_idempotency_key: str | None,
    draft_request_fingerprint: str | None,
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
        draft_idempotency_key=draft_idempotency_key,
        draft_request_fingerprint=draft_request_fingerprint,
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


def create_manual_expense(
    db: Session, payload: ExpenseManualCreateRequest, auth: AuthContext
) -> Expense:
    tenant_id = auth.tenant_id
    if not payload.client_ref:
        # No client-supplied ref (absent, or empty-string from a client bug) — no
        # dedup; every call is a fresh row. Unchanged pre-#65 behavior. Treating ""
        # as "no ref" (not as the key "{device_id}:") avoids both a 422 on a real
        # expense and silently collapsing distinct creates into one.
        return _insert_manual_expense(
            db,
            payload,
            tenant_id,
            draft_idempotency_key=None,
            draft_request_fingerprint=None,
        )

    # Issue #65 slice 1: device-scoped idempotent create. The composite key lives in
    # the expense's own ``draft_idempotency_key`` (unique per tenant) so slice 3 can
    # later resolve a ``local:{client_ref}`` mutation by it; the device prefix is built
    # server-side from the authenticated token, never trusted from the body.
    key = local_ref_storage_key(auth.device_id, payload.client_ref)
    fingerprint = _manual_request_fingerprint(payload)
    existing = _find_manual_expense_by_key(db, tenant_id, key)
    if existing is not None:
        return _resolve_existing_manual_create(existing, fingerprint)
    try:
        return _insert_manual_expense(
            db,
            payload,
            tenant_id,
            draft_idempotency_key=key,
            draft_request_fingerprint=fingerprint,
        )
    except IntegrityError:
        # A concurrent request won the (tenant_id, draft_idempotency_key) unique race
        # between our lookup and flush — re-read and treat it as the canonical row.
        db.rollback()
        existing = _find_manual_expense_by_key(db, tenant_id, key)
        if existing is not None:
            return _resolve_existing_manual_create(existing, fingerprint)
        raise


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
        notification_key=payload.notification_key,
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
        source=f"{NOTIFICATION_DRAFT_SOURCE_PREFIX}{source_label}",
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
