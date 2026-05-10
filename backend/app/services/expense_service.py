from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Expense
from app.schemas import (
    ExpenseManualCreateRequest,
    ExpenseRecognizeTextRequest,
    ExpenseUpdateRequest,
)
from app.services.category_service import normalize_category
from app.services.classify_service import classify_expense
from app.services.cleanup_service import cleanup_after_confirm
from app.services.duplicate_service import (
    list_suspected_duplicates,
    mark_duplicate_status,
    mark_not_duplicate,
)
from app.services.file_service import SavedUpload, delete_relative_upload
from app.services.ocr_service import (
    OcrResult,
    apply_ocr_result,
    clear_ocr_draft_fields,
    collect_auto_ocr_results,
    retry_ocr,
    run_auto_ocr,
)
from app.services.thumb_service import generate_thumbnail, resolve_protected_thumbnail
from app.services.stats_service import _confirmed_ordered, _confirmed_query
from app.services.time_service import ensure_utc, now_utc


EDITABLE_STATUSES = {"pending", "confirmed"}


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


def _try_generate_thumbnail(relative_path: str | None, tenant_id: str) -> str | None:
    try:
        return generate_thumbnail(relative_path, tenant_id=tenant_id)
    except Exception:
        return None


def _apply_pending_enrichment(db: Session, expense: Expense) -> None:
    if not expense.thumbnail_path:
        expense.thumbnail_path = _try_generate_thumbnail(
            expense.image_path, expense.tenant_id
        )
    run_auto_ocr(expense)
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
            select(Expense)
            .where(Expense.id == expense_id)
            .where(Expense.tenant_id == tenant_id)
        )
        if expense is None or expense.status != "pending":
            return

        ocr_results = collect_auto_ocr_results(expense, timezone_name=timezone_name)
        try:
            db.refresh(expense)
            if expense.status != "pending":
                return
            if not expense.thumbnail_path:
                expense.thumbnail_path = _try_generate_thumbnail(
                    expense.image_path, expense.tenant_id
                )
            for result in ocr_results:
                apply_ocr_result(expense, result, timezone_name=timezone_name)
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


def create_manual_expense(
    db: Session, payload: ExpenseManualCreateRequest, tenant_id: str
) -> Expense:
    if payload.amount_cents is None:
        raise AppError("amount_required", status_code=400)

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
        expense_time=ensure_utc(payload.expense_time) or now,
        created_at=now,
        updated_at=now,
        confirmed_at=now,
        tags=_clean_optional_text(payload.tags),
        value_score=payload.value_score,
        regret_score=payload.regret_score,
    )
    if expense.category == "其他":
        classify_expense(db, expense)
    db.add(expense)
    db.flush()
    mark_duplicate_status(db, expense)
    db.commit()
    db.refresh(expense)
    return expense


def get_expense(db: Session, expense_id: int, tenant_id: str) -> Expense:
    expense = db.scalar(
        select(Expense)
        .where(Expense.id == expense_id)
        .where(Expense.tenant_id == tenant_id)
    )
    if expense is None:
        raise AppError("expense_not_found", status_code=404)
    return expense


def list_pending(db: Session, tenant_id: str) -> list[Expense]:
    return list(
        db.scalars(
            select(Expense)
            .where(Expense.tenant_id == tenant_id)
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
    timezone_name: str | None = None,
) -> tuple[list[Expense], int]:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 200)

    query = _confirmed_query(
        tenant_id=tenant_id, month=month, category=category, timezone_name=timezone_name
    )
    total = int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    expenses = list(
        db.scalars(
            _confirmed_ordered(query).offset((page - 1) * page_size).limit(page_size)
        )
    )
    return expenses, total


def update_expense(
    db: Session, expense_id: int, tenant_id: str, payload: ExpenseUpdateRequest
) -> Expense:
    expense = get_expense(db, expense_id, tenant_id)
    if expense.status not in EDITABLE_STATUSES:
        raise AppError("expense_not_found", status_code=404)

    updates = payload.model_dump(exclude_unset=True)
    if "amount_cents" in updates:
        expense.amount_cents = updates["amount_cents"]
    if "merchant" in updates:
        expense.merchant = _clean_optional_text(updates["merchant"])
    if "category" in updates and updates["category"]:
        expense.category = _clean_category(updates["category"])
    if "note" in updates:
        expense.note = _clean_text(updates["note"])
    if "expense_time" in updates:
        expense.expense_time = ensure_utc(updates["expense_time"])
    if "tags" in updates:
        expense.tags = _clean_optional_text(updates["tags"])
    if "value_score" in updates:
        expense.value_score = updates["value_score"]
    if "regret_score" in updates:
        expense.regret_score = updates["regret_score"]

    clear_ocr_draft_fields(expense, list(updates.keys()))

    should_auto_classify = (
        "category" not in updates
        and expense.category == "其他"
        and any(field in updates for field in {"merchant", "note"})
    )
    if should_auto_classify:
        classify_expense(db, expense)

    if any(field in updates for field in {"amount_cents", "merchant", "expense_time"}):
        mark_duplicate_status(db, expense)

    expense.updated_at = now_utc()
    db.commit()
    db.refresh(expense)
    return expense


def confirm_expense(db: Session, expense_id: int, tenant_id: str) -> Expense:
    expense = get_expense(db, expense_id, tenant_id)
    if expense.status == "rejected":
        raise AppError("expense_not_found", status_code=404)
    if expense.amount_cents is None:
        raise AppError("amount_required", status_code=400)
    if expense.status == "confirmed":
        return expense

    now = now_utc()
    expense.status = "confirmed"
    expense.confirmed_at = now
    expense.updated_at = now
    cleanup_after_confirm(expense)
    db.commit()
    db.refresh(expense)
    return expense


def reject_expense(db: Session, expense_id: int, tenant_id: str) -> Expense:
    expense = get_expense(db, expense_id, tenant_id)
    if expense.status != "pending":
        raise AppError("expense_not_found", status_code=404)

    now = now_utc()
    expense.status = "rejected"
    expense.rejected_at = now
    expense.updated_at = now
    db.commit()
    db.refresh(expense)
    return expense


def ensure_thumbnail_file(
    db: Session, expense_id: int, tenant_id: str
) -> tuple[Path, str]:
    expense = get_expense(db, expense_id, tenant_id)
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


def retry_expense_ocr(db: Session, expense_id: int, tenant_id: str) -> Expense:
    expense = get_expense(db, expense_id, tenant_id)
    if expense.status == "rejected":
        raise AppError("expense_not_found", status_code=404)

    retry_ocr(expense)
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
    db.refresh(expense)
    return expense


def recognize_expense_text(
    db: Session, expense_id: int, tenant_id: str, payload: ExpenseRecognizeTextRequest
) -> Expense:
    expense = get_expense(db, expense_id, tenant_id)
    if expense.status == "rejected":
        raise AppError("expense_not_found", status_code=404)

    raw_text = payload.raw_text.strip()
    apply_ocr_result(expense, OcrResult(raw_text=raw_text, confidence=None))
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
