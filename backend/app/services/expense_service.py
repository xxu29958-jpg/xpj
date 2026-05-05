from __future__ import annotations

from collections import defaultdict
import csv
from datetime import datetime, timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path

from sqlalchemy import Select, false, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.models import Expense
from app.schemas import ExpenseManualCreateRequest, ExpenseRecognizeTextRequest, ExpenseUpdateRequest
from app.services.category_service import merge_categories, normalize_category
from app.services.classify_service import classify_expense
from app.services.cleanup_service import cleanup_after_confirm
from app.services.duplicate_service import (
    list_suspected_duplicates,
    mark_duplicate_status,
    mark_not_duplicate,
)
from app.services.file_service import SavedUpload, delete_relative_upload
from app.services.ocr_service import retry_ocr, run_auto_ocr
from app.services.receipt_parse_service import parse_receipt_text
from app.services.thumb_service import generate_thumbnail, resolve_protected_thumbnail
from app.services.time_service import ensure_utc, local_month_bounds_utc, local_month_label, now_utc


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


def _try_generate_thumbnail(relative_path: str | None) -> str | None:
    try:
        return generate_thumbnail(relative_path)
    except Exception:
        return None


def create_pending_expense(db: Session, saved_file: SavedUpload, tenant_id: str, *, source: str = "iPhone截图") -> Expense:
    now = now_utc()
    thumbnail_path = _try_generate_thumbnail(saved_file.relative_path)
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
        run_auto_ocr(expense)
        if expense.category == "其他":
            classify_expense(db, expense)
        mark_duplicate_status(db, expense)
        expense.updated_at = now_utc()
        db.commit()
        db.refresh(expense)
        return expense
    except Exception:
        db.rollback()
        delete_relative_upload(thumbnail_path)
        delete_relative_upload(saved_file.relative_path)
        raise


def create_manual_expense(db: Session, payload: ExpenseManualCreateRequest, tenant_id: str) -> Expense:
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
    expense = db.scalar(select(Expense).where(Expense.id == expense_id).where(Expense.tenant_id == tenant_id))
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


def _base_confirmed_query(tenant_id: str) -> Select[tuple[Expense]]:
    return select(Expense).where(Expense.tenant_id == tenant_id).where(Expense.status == "confirmed")


def _stat_time_expr():
    return func.coalesce(Expense.expense_time, Expense.confirmed_at)


def _stat_time(expense: Expense) -> datetime | None:
    return ensure_utc(expense.expense_time) or ensure_utc(expense.confirmed_at)


def _stat_month_bounds(month: str) -> tuple[datetime, datetime] | None:
    return local_month_bounds_utc(month, get_settings().ocr_default_timezone)


def _confirmed_query(
    *,
    tenant_id: str,
    month: str | None = None,
    category: str | None = None,
) -> Select[tuple[Expense]]:
    query = _base_confirmed_query(tenant_id)
    if category:
        query = query.where(Expense.category == normalize_category(category))
    if month:
        bounds = _stat_month_bounds(month)
        if bounds is None:
            return query.where(false())
        start_utc, end_utc = bounds
        query = query.where(_stat_time_expr() >= start_utc).where(_stat_time_expr() < end_utc)
    return query


def _confirmed_ordered(query: Select[tuple[Expense]]) -> Select[tuple[Expense]]:
    return query.order_by(_stat_time_expr().desc(), Expense.id.desc())


def list_confirmed(
    db: Session,
    *,
    tenant_id: str,
    page: int = 1,
    page_size: int = 50,
    month: str | None = None,
    category: str | None = None,
) -> tuple[list[Expense], int]:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 200)

    query = _confirmed_query(tenant_id=tenant_id, month=month, category=category)
    total = int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    expenses = list(
        db.scalars(
            _confirmed_ordered(query)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return expenses, total


def _filtered_confirmed(
    db: Session,
    *,
    tenant_id: str,
    month: str | None = None,
    category: str | None = None,
) -> list[Expense]:
    return list(db.scalars(_confirmed_ordered(_confirmed_query(tenant_id=tenant_id, month=month, category=category))))


def list_categories(db: Session, tenant_id: str) -> list[str]:
    return merge_categories(
        list(db.scalars(select(Expense.category).where(Expense.tenant_id == tenant_id).distinct()))
    )


def list_months(db: Session, tenant_id: str) -> list[str]:
    timezone_name = get_settings().ocr_default_timezone
    expenses = db.scalars(
        select(Expense)
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.status == "confirmed")
        .where(_stat_time_expr().is_not(None))
    )
    months = {
        label
        for expense in expenses
        if (label := local_month_label(_stat_time(expense), timezone_name)) is not None
    }
    return sorted(months, reverse=True)


def export_confirmed_csv(
    db: Session,
    *,
    tenant_id: str,
    month: str | None = None,
    category: str | None = None,
) -> str:
    expenses = _filtered_confirmed(db, tenant_id=tenant_id, month=month, category=category)
    output = StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        [
            "id",
            "public_id",
            "amount_cents",
            "amount_yuan",
            "merchant",
            "category",
            "note",
            "source",
            "expense_time",
            "confirmed_at",
            "tags",
            "value_score",
            "regret_score",
        ]
    )
    for expense in expenses:
        amount_cents = expense.amount_cents or 0
        amount_yuan = (Decimal(amount_cents) / Decimal(100)).quantize(Decimal("0.01"))
        stat_time = _stat_time(expense)
        confirmed_at = ensure_utc(expense.confirmed_at)
        writer.writerow(
            [
                expense.id,
                expense.public_id,
                amount_cents,
                str(amount_yuan),
                expense.merchant or "",
                expense.category,
                expense.note or "",
                expense.source,
                stat_time.isoformat().replace("+00:00", "Z") if stat_time else "",
                confirmed_at.isoformat().replace("+00:00", "Z") if confirmed_at else "",
                expense.tags or "",
                expense.value_score or "",
                expense.regret_score or "",
            ]
        )
    return output.getvalue()


def update_expense(db: Session, expense_id: int, tenant_id: str, payload: ExpenseUpdateRequest) -> Expense:
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


def ensure_thumbnail_file(db: Session, expense_id: int, tenant_id: str) -> tuple[Path, str]:
    expense = get_expense(db, expense_id, tenant_id)
    resolved = resolve_protected_thumbnail(expense.thumbnail_path)
    if resolved is not None:
        return resolved

    thumbnail_path = generate_thumbnail(expense.image_path)
    if thumbnail_path is not None:
        expense.thumbnail_path = thumbnail_path
        expense.thumbnail_deleted_at = None
        expense.updated_at = now_utc()
        db.commit()
        db.refresh(expense)

    resolved = resolve_protected_thumbnail(expense.thumbnail_path)
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
    if expense.amount_cents is not None or expense.merchant or expense.expense_time is not None:
        mark_duplicate_status(db, expense)
    expense.updated_at = now_utc()
    db.commit()
    db.refresh(expense)
    return expense


def recognize_expense_text(db: Session, expense_id: int, tenant_id: str, payload: ExpenseRecognizeTextRequest) -> Expense:
    expense = get_expense(db, expense_id, tenant_id)
    if expense.status == "rejected":
        raise AppError("expense_not_found", status_code=404)

    raw_text = payload.raw_text.strip()
    parsed = parse_receipt_text(raw_text)
    expense.raw_text = raw_text
    expense.confidence = parsed.confidence
    if expense.amount_cents is None and parsed.amount_cents is not None:
        expense.amount_cents = parsed.amount_cents
    if not (expense.merchant or "").strip() and parsed.merchant:
        expense.merchant = parsed.merchant
    if expense.expense_time is None and parsed.expense_time is not None:
        expense.expense_time = parsed.expense_time
    if expense.category == "其他" and parsed.category:
        expense.category = parsed.category
    if expense.category == "其他":
        classify_expense(db, expense)
    if expense.amount_cents is not None or expense.merchant or expense.expense_time is not None:
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


def monthly_stats(db: Session, month: str, tenant_id: str) -> dict:
    by_category: dict[str, dict[str, int | str]] = defaultdict(lambda: {"category": "", "amount_cents": 0, "count": 0})

    total_amount_cents = 0
    total_count = 0
    bounds = _stat_month_bounds(month)
    if bounds is None:
        return {
            "month": month,
            "total_amount_cents": 0,
            "count": 0,
            "by_category": [],
        }
    start_utc, end_utc = bounds
    rows = db.execute(
        select(
            Expense.category,
            func.coalesce(func.sum(Expense.amount_cents), 0),
            func.count(Expense.id),
        )
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.status == "confirmed")
        .where(_stat_time_expr() >= start_utc)
        .where(_stat_time_expr() < end_utc)
        .group_by(Expense.category)
    )
    for category_value, amount_value, count_value in rows:
        amount = int(amount_value or 0)
        count = int(count_value or 0)
        total_amount_cents += amount
        total_count += count
        category = normalize_category(category_value)
        bucket = by_category[category]
        bucket["category"] = category
        bucket["amount_cents"] = int(bucket["amount_cents"]) + amount
        bucket["count"] = int(bucket["count"]) + count

    return {
        "month": month,
        "total_amount_cents": total_amount_cents,
        "count": total_count,
        "by_category": sorted(
            by_category.values(),
            key=lambda item: int(item["amount_cents"]),
            reverse=True,
        ),
    }


def lifestyle_stats(db: Session, month: str, tenant_id: str) -> dict:
    month_expenses = list(db.scalars(_confirmed_query(tenant_id=tenant_id, month=month)))
    recent_start = now_utc() - timedelta(days=7)

    ai_subscription_amount_cents = sum(
        item.amount_cents or 0 for item in month_expenses if normalize_category(item.category) == "AI订阅"
    )
    digital_amount_cents = sum(
        item.amount_cents or 0 for item in month_expenses if normalize_category(item.category) == "数码"
    )
    max_expense = max(month_expenses, key=lambda item: item.amount_cents or 0, default=None)
    recent_7_days_amount_cents = int(
        db.scalar(
            select(func.coalesce(func.sum(Expense.amount_cents), 0))
            .where(Expense.tenant_id == tenant_id)
            .where(Expense.status == "confirmed")
            .where(_stat_time_expr() >= recent_start)
        )
        or 0
    )

    merchant_counts: dict[str, int] = defaultdict(int)
    for item in month_expenses:
        merchant = (item.merchant or "").strip()
        if merchant:
            merchant_counts[merchant] += 1

    frequent_merchants = [
        {"merchant": merchant, "count": count}
        for merchant, count in sorted(merchant_counts.items(), key=lambda pair: (-pair[1], pair[0]))[:5]
    ]

    return {
        "month": month,
        "ai_subscription_amount_cents": ai_subscription_amount_cents,
        "digital_amount_cents": digital_amount_cents,
        "max_expense": max_expense,
        "recent_7_days_amount_cents": recent_7_days_amount_cents,
        "frequent_merchants": frequent_merchants,
    }
