from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.fx_constants import FX_STATUS_PENDING
from app.ledger_scope import ledger_scoped_select
from app.models import Expense
from app.schemas import (
    ConfirmedExpenseBatchUpdateRequest,
    ConfirmedExpenseBatchUpdateResponse,
    ExpenseManualCreateRequest,
    NotificationDraftCreateRequest,
    ExpenseRecognizeTextRequest,
    ExpenseUpdateRequest,
)
from app.services.category_service import normalize_category
from app.services.classify_service import classify_expense
from app.services.cleanup_service import cleanup_after_confirm
from app.services.duplicate_service import (
    clear_duplicate_references_to,
    list_suspected_duplicates,
    mark_duplicate_status,
    mark_not_duplicate,
    revalidate_duplicate_references_to,
)
from app.services.exchange_rate_service import apply_currency_payload, refresh_currency_snapshot
from app.services.file_service import SavedUpload, delete_relative_upload, resolve_protected_image
from app.services.ocr_service import (
    OcrResult,
    apply_ocr_result,
    clear_ocr_draft_fields,
    collect_auto_ocr_results,
    extract_ocr_result,
    run_auto_ocr,
    serialize_ocr_draft_fields,
)
from app.services.receipt_parse_service import parse_receipt_text
from app.services.spending_contract_service import confirmed_ordered, confirmed_query
from app.services.thumb_service import generate_thumbnail, resolve_protected_thumbnail
from app.services.tag_service import normalize_tags, sync_expense_tags
from app.services.time_service import ensure_utc, now_utc


EDITABLE_STATUSES = {"pending", "confirmed"}
NOTIFICATION_DRAFT_WINDOW_MINUTES = 30
NOTIFICATION_DRAFT_SOURCE_LABELS = {
    "wechat": "微信",
    "alipay": "支付宝",
    "bank_sms": "银行短信",
    "bank_app": "银行 App",
    "other": "其他通知",
}


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip()


def _clean_category(value: str | None) -> str:
    return normalize_category(value)


def _clean_notification_source(value: str) -> str:
    cleaned = value.strip().lower().replace("-", "_")
    if cleaned not in NOTIFICATION_DRAFT_SOURCE_LABELS:
        raise AppError("notification_source_invalid", status_code=422)
    return cleaned


def _notification_window_key(expense_time, *, fallback_now) -> str:
    when = ensure_utc(expense_time or fallback_now)
    minute = (when.minute // NOTIFICATION_DRAFT_WINDOW_MINUTES) * NOTIFICATION_DRAFT_WINDOW_MINUTES
    bucket = when.replace(minute=minute, second=0, microsecond=0)
    return bucket.isoformat()


def _notification_draft_key(
    *,
    source: str,
    merchant: str | None,
    amount_cents: int | None,
    original_currency: str | None,
    original_amount: object | None,
    expense_time,
    now,
) -> str:
    merchant_key = _clean_optional_text(merchant) or ""
    material = "|".join(
        [
            "notification",
            source,
            merchant_key.casefold(),
            str(amount_cents) if amount_cents is not None else "",
            (original_currency or "").strip().upper(),
            str(original_amount) if original_amount is not None else "",
            _notification_window_key(expense_time, fallback_now=now),
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _notification_draft_fields(payload: NotificationDraftCreateRequest) -> str | None:
    fields: set[str] = set()
    if payload.amount_cents is not None:
        fields.add("amount_cents")
    if payload.original_amount is not None or payload.original_amount_minor is not None:
        fields.add("original_amount")
    if payload.original_currency or payload.original_currency_code:
        fields.add("original_currency")
    if _clean_optional_text(payload.merchant):
        fields.add("merchant")
    if payload.expense_time is not None or payload.spent_at is not None:
        fields.add("expense_time")
    if _clean_optional_text(payload.category):
        fields.add("category")
    if not fields:
        return None
    return serialize_ocr_draft_fields(list(fields))


def _try_generate_thumbnail(relative_path: str | None, tenant_id: str) -> str | None:
    try:
        return generate_thumbnail(relative_path, tenant_id=tenant_id)
    except Exception:
        return None


def _expense_has_pending_fx(expense: Expense) -> bool:
    return expense.fx_status == FX_STATUS_PENDING or (
        expense.amount_cents is None and expense.original_amount_minor is not None
    )


def _updated_at_matches(value):
    if value is None:
        return Expense.updated_at.is_(None)
    return Expense.updated_at == value


def _claim_pending_expense_for_ocr(
    db: Session,
    *,
    expense_id: int,
    tenant_id: str,
    expected_updated_at,
    claimed_at,
) -> Expense:
    result = db.execute(
        update(Expense)
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.id == expense_id)
        .where(Expense.status == "pending")
        .where(_updated_at_matches(expected_updated_at))
        .values(updated_at=claimed_at)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.expire_all()
        current = db.scalar(
            ledger_scoped_select(Expense, tenant_id).where(Expense.id == expense_id)
        )
        if current is None or current.status != "pending":
            raise AppError("expense_not_found", status_code=404)
        raise AppError(
            "expense_changed",
            "账单已被修改，请重新打开后再识别。",
            status_code=409,
        )
    db.expire_all()
    return get_expense(db, expense_id, tenant_id)


def _ensure_expense_can_confirm(expense: Expense) -> None:
    if _expense_has_pending_fx(expense):
        raise AppError("exchange_rate_pending", status_code=409)
    if expense.amount_cents is None:
        raise AppError("amount_required", status_code=400)


def _apply_pending_enrichment(db: Session, expense: Expense) -> None:
    if not expense.thumbnail_path:
        expense.thumbnail_path = _try_generate_thumbnail(
            expense.image_path, expense.tenant_id
        )
    run_auto_ocr(expense)
    _replace_ocr_draft_items_from_text(db, expense, expense.raw_text or "")
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

        ocr_results = collect_auto_ocr_results(expense, timezone_name=timezone_name)

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
            for result in ocr_results:
                apply_ocr_result(expense, result, timezone_name=timezone_name)
                _replace_ocr_draft_items_from_text(
                    db, expense, result.raw_text, timezone_name=timezone_name
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
            db.rollback()


def _begin_immediate_write_if_sqlite(db: Session) -> None:
    bind = db.get_bind()
    if bind.dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))


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


def get_expense(db: Session, expense_id: int, tenant_id: str) -> Expense:
    expense = db.scalar(
        ledger_scoped_select(Expense, tenant_id).where(Expense.id == expense_id)
    )
    if expense is None:
        raise AppError("expense_not_found", status_code=404)
    return expense


def list_pending(db: Session, tenant_id: str) -> list[Expense]:
    return list(
        db.scalars(
            ledger_scoped_select(Expense, tenant_id)
            .where(Expense.status == "pending")
            .order_by(Expense.created_at.desc(), Expense.id.desc())
        )
    )


def list_confirmed(
    db: Session,
    *,
    tenant_id: str,
    page: int = 1,
    page_size: int = 50,
    month: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    timezone_name: str | None = None,
) -> tuple[list[Expense], int]:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 200)

    query = confirmed_query(
        tenant_id=tenant_id,
        month=month,
        category=category,
        tag=tag,
        timezone_name=timezone_name,
    )
    total = int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    expenses = list(
        db.scalars(
            confirmed_ordered(query).offset((page - 1) * page_size).limit(page_size)
        )
    )
    return expenses, total


def batch_update_confirmed_expenses(
    db: Session,
    *,
    tenant_id: str,
    payload: ConfirmedExpenseBatchUpdateRequest,
) -> ConfirmedExpenseBatchUpdateResponse:
    expense_ids = list(dict.fromkeys(payload.expense_ids))
    category_provided = payload.category is not None
    tags_provided = payload.tags is not None
    if not category_provided and not tags_provided:
        raise AppError("invalid_request", status_code=422)

    category = payload.category.strip() if category_provided else None
    if category_provided and not category:
        raise AppError("invalid_request", status_code=422)

    normalized_tags = normalize_tags(payload.tags) if tags_provided else None
    rows = list(
        db.scalars(
            select(Expense)
            .where(Expense.tenant_id == tenant_id)
            .where(Expense.id.in_(expense_ids))
        )
    )
    rows_by_id = {row.id: row for row in rows}

    updated_count = 0
    skipped_not_found = 0
    skipped_not_confirmed = 0
    now = now_utc()
    for expense_id in expense_ids:
        expense = rows_by_id.get(expense_id)
        if expense is None:
            skipped_not_found += 1
            continue
        if expense.status != "confirmed":
            skipped_not_confirmed += 1
            continue
        if category_provided:
            expense.category = _clean_category(category)
        if tags_provided:
            expense.tags = normalized_tags
            sync_expense_tags(db, expense)
        expense.updated_at = now
        updated_count += 1

    if updated_count:
        db.commit()

    return ConfirmedExpenseBatchUpdateResponse(
        requested_count=len(expense_ids),
        updated_count=updated_count,
        skipped_not_found=skipped_not_found,
        skipped_not_confirmed=skipped_not_confirmed,
    )


def update_expense(
    db: Session, expense_id: int, tenant_id: str, payload: ExpenseUpdateRequest
) -> Expense:
    expense = get_expense(db, expense_id, tenant_id)
    if expense.status not in EDITABLE_STATUSES:
        raise AppError("expense_not_found", status_code=404)

    updates = payload.model_dump(exclude_unset=True)
    if "merchant" in updates:
        expense.merchant = _clean_optional_text(updates["merchant"])
    if "category" in updates and updates["category"]:
        expense.category = _clean_category(updates["category"])
    if "note" in updates:
        expense.note = _clean_text(updates["note"])
    if "spent_at" in updates:
        expense.expense_time = ensure_utc(updates["spent_at"])
    elif "expense_time" in updates:
        expense.expense_time = ensure_utc(updates["expense_time"])
    if "tags" in updates:
        expense.tags = normalize_tags(updates["tags"])
    if "value_score" in updates:
        expense.value_score = updates["value_score"]
    if "regret_score" in updates:
        expense.regret_score = updates["regret_score"]
    apply_currency_payload(
        db,
        tenant_id=tenant_id,
        expense=expense,
        payload=payload,
        amount_was_explicit="amount_cents" in updates,
    )
    if expense.status == "confirmed":
        _ensure_expense_can_confirm(expense)

    clear_ocr_draft_fields(expense, list(updates.keys()))

    should_auto_classify = (
        "category" not in updates
        and expense.category == "其他"
        and any(field in updates for field in {"merchant", "note"})
    )
    if should_auto_classify:
        classify_expense(db, expense)

    if any(
        field in updates
        for field in {
            "amount_cents",
            "original_currency",
            "original_amount",
            "original_currency_code",
            "original_amount_minor",
            "exchange_rate_date",
            "merchant",
            "spent_at",
            "expense_time",
        }
    ):
        mark_duplicate_status(db, expense)
        db.flush()
        revalidate_duplicate_references_to(db, tenant_id=tenant_id, duplicate_of_id=expense.id)
    if "tags" in updates:
        sync_expense_tags(db, expense)

    expense.updated_at = now_utc()
    db.commit()
    db.refresh(expense)
    return expense


def confirm_expense(db: Session, expense_id: int, tenant_id: str) -> Expense:
    expense = get_expense(db, expense_id, tenant_id)
    if expense.status == "confirmed":
        return expense
    if expense.status != "pending":
        raise AppError("expense_not_found", status_code=404)
    if _expense_has_pending_fx(expense):
        refresh_currency_snapshot(db, tenant_id=tenant_id, expense=expense)
    _ensure_expense_can_confirm(expense)
    db.flush()

    now = now_utc()
    result = db.execute(
        update(Expense)
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.id == expense_id)
        .where(Expense.status == "pending")
        .where(Expense.amount_cents.is_not(None))
        .values(status="confirmed", confirmed_at=now, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.expire_all()
        expense = get_expense(db, expense_id, tenant_id)
        if expense.status == "confirmed":
            return expense
        if expense.status == "pending":
            _ensure_expense_can_confirm(expense)
        raise AppError("expense_not_found", status_code=404)

    db.expire_all()
    expense = get_expense(db, expense_id, tenant_id)
    sync_expense_tags(db, expense)
    db.commit()
    db.refresh(expense)
    if cleanup_after_confirm(expense):
        db.commit()
        db.refresh(expense)
    return expense


def reject_expense(db: Session, expense_id: int, tenant_id: str) -> Expense:
    now = now_utc()
    result = db.execute(
        update(Expense)
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.id == expense_id)
        .where(Expense.status == "pending")
        .values(status="rejected", rejected_at=now, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.expire_all()
        existing = get_expense(db, expense_id, tenant_id)
        if existing.status == "rejected":
            return existing
        raise AppError("expense_not_found", status_code=404)

    db.expire_all()
    expense = get_expense(db, expense_id, tenant_id)
    clear_duplicate_references_to(db, tenant_id=tenant_id, duplicate_of_id=expense.id)
    db.commit()
    db.refresh(expense)
    return expense


def ensure_thumbnail_file(
    db: Session, expense_id: int, tenant_id: str
) -> tuple[Path, str]:
    expense = get_expense(db, expense_id, tenant_id)
    if expense.image_deleted_at is not None:
        raise AppError("image_not_found", status_code=404)
    if expense.thumbnail_deleted_at is not None:
        raise AppError("image_not_found", status_code=404)
    resolved = resolve_protected_thumbnail(expense.thumbnail_path, tenant_id)
    if resolved is not None:
        return resolved

    thumbnail_path = generate_thumbnail(expense.image_path, tenant_id=tenant_id)
    if thumbnail_path is not None:
        expense.thumbnail_path = thumbnail_path
        expense.thumbnail_deleted_at = None
        expense.updated_at = now_utc()
        db.commit()
        db.refresh(expense)

    resolved = resolve_protected_thumbnail(expense.thumbnail_path, tenant_id)
    if resolved is None:
        raise AppError("image_not_found", status_code=404)
    return resolved


def ensure_image_file(
    db: Session, expense_id: int, tenant_id: str
) -> tuple[Path, str]:
    expense = get_expense(db, expense_id, tenant_id)
    if expense.image_deleted_at is not None:
        raise AppError("image_not_found", status_code=404)
    return resolve_protected_image(expense.image_path, tenant_id)


def _replace_ocr_draft_items_from_text(
    db: Session,
    expense: Expense,
    raw_text: str,
    *,
    timezone_name: str | None = None,
) -> None:
    if expense.status != "pending":
        return
    parsed = parse_receipt_text(raw_text, timezone_name=timezone_name)

    from app.services.receipt_item_service import replace_ocr_draft_items

    replace_ocr_draft_items(db, expense, parsed.items)


def retry_expense_ocr(db: Session, expense_id: int, tenant_id: str) -> Expense:
    expense = get_expense(db, expense_id, tenant_id)
    if expense.status != "pending":
        raise AppError("expense_not_found", status_code=404)

    expected_updated_at = expense.updated_at
    result = extract_ocr_result(expense)
    now = now_utc()
    expense = _claim_pending_expense_for_ocr(
        db,
        expense_id=expense_id,
        tenant_id=tenant_id,
        expected_updated_at=expected_updated_at,
        claimed_at=now,
    )
    # Keep legacy OCR draft-field detection anchored to the pre-claim snapshot.
    expense.updated_at = expected_updated_at
    apply_ocr_result(expense, result)
    _replace_ocr_draft_items_from_text(db, expense, expense.raw_text or "")
    if expense.category == "其他":
        classify_expense(db, expense)
    if (
        expense.amount_cents is not None
        or expense.merchant
        or expense.expense_time is not None
    ):
        mark_duplicate_status(db, expense)
    expense.updated_at = now
    db.commit()
    db.refresh(expense)
    return expense


def recognize_expense_text(
    db: Session, expense_id: int, tenant_id: str, payload: ExpenseRecognizeTextRequest
) -> Expense:
    expense = get_expense(db, expense_id, tenant_id)
    if expense.status != "pending":
        raise AppError("expense_not_found", status_code=404)

    raw_text = payload.raw_text.strip()
    expected_updated_at = expense.updated_at
    now = now_utc()
    expense = _claim_pending_expense_for_ocr(
        db,
        expense_id=expense_id,
        tenant_id=tenant_id,
        expected_updated_at=expected_updated_at,
        claimed_at=now,
    )
    # Keep legacy OCR draft-field detection anchored to the pre-claim snapshot.
    expense.updated_at = expected_updated_at
    apply_ocr_result(expense, OcrResult(raw_text=raw_text, confidence=None))
    _replace_ocr_draft_items_from_text(db, expense, raw_text)
    if expense.category == "其他":
        classify_expense(db, expense)
    if (
        expense.amount_cents is not None
        or expense.merchant
        or expense.expense_time is not None
    ):
        mark_duplicate_status(db, expense)
    expense.updated_at = now
    db.commit()
    db.refresh(expense)
    return expense


def list_duplicate_expenses(db: Session, tenant_id: str) -> list[Expense]:
    return list_suspected_duplicates(db, tenant_id)


def mark_expense_not_duplicate(db: Session, expense_id: int, tenant_id: str) -> Expense:
    expense = get_expense(db, expense_id, tenant_id)
    mark_not_duplicate(db, expense)
    expense.updated_at = now_utc()
    db.commit()
    db.refresh(expense)
    return expense
