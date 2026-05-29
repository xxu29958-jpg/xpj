from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import DuplicateIgnore, Expense
from app.services.time_service import ensure_utc

ACTIVE_DUPLICATE_IGNORE_KINDS = ("image_hash", "image_perceptual_hash", "similar")


def mark_duplicate_status(db: Session, expense: Expense) -> Expense:
    duplicate = _find_same_image(db, expense)
    if duplicate is not None:
        expense.duplicate_status = "suspected"
        expense.duplicate_of_id = duplicate.id
        expense.duplicate_reason = "图片 hash 完全一致，可能是重复截图。"
        return expense

    duplicate = _find_visually_similar_image(db, expense)
    if duplicate is not None:
        expense.duplicate_status = "suspected"
        expense.duplicate_of_id = duplicate.id
        expense.duplicate_reason = "图片感知 hash 接近，可能是重复截图。"
        return expense

    duplicate = _find_similar_expense(db, expense)
    if duplicate is not None:
        expense.duplicate_status = "suspected"
        expense.duplicate_of_id = duplicate.id
        expense.duplicate_reason = "金额、商家和消费时间接近，可能是重复账单。"
        return expense

    expense.duplicate_status = "none"
    expense.duplicate_of_id = None
    expense.duplicate_reason = None
    return expense


def _find_same_image(db: Session, expense: Expense) -> Expense | None:
    if not expense.image_hash:
        return None

    candidates = db.scalars(
        select(Expense)
        .where(Expense.id != expense.id)
        .where(Expense.tenant_id == expense.tenant_id)
        .where(Expense.status != "rejected")
        .where(Expense.image_hash == expense.image_hash)
        .order_by(Expense.created_at.asc())
    )
    for candidate in candidates:
        if not _is_duplicate_ignored(db, expense.tenant_id, expense.id, candidate.id, "image_hash"):
            return candidate
    return None


def _find_visually_similar_image(db: Session, expense: Expense) -> Expense | None:
    match: Expense | None = None
    if expense.image_perceptual_hash:
        # Bounded scan over the most-recent phash-bearing expenses: Hamming
        # distance can't be a SQL predicate, so we sweep candidates in Python.
        # A re-upload's near-duplicate is almost always recent, so newest-first
        # within a configured cap maximises catch rate while keeping the upload
        # path O(limit) instead of O(ledger size) (ENGINEERING_RULES §12).
        candidates = db.scalars(
            select(Expense)
            .where(Expense.id != expense.id)
            .where(Expense.tenant_id == expense.tenant_id)
            .where(Expense.status != "rejected")
            .where(Expense.image_perceptual_hash.is_not(None))
            .order_by(Expense.created_at.desc())
            .limit(get_settings().duplicate_phash_scan_limit)
        )
        for candidate in candidates:
            if _is_duplicate_ignored(
                db,
                expense.tenant_id,
                expense.id,
                candidate.id,
                "image_perceptual_hash",
            ):
                continue
            if _phash_distance(expense.image_perceptual_hash, candidate.image_perceptual_hash) <= 5:
                match = candidate
                break
    return match


def _phash_distance(left: str | None, right: str | None) -> int:
    if not left or not right:
        return 64
    try:
        return (int(left, 16) ^ int(right, 16)).bit_count()
    except ValueError:
        return 64


def _find_similar_expense(db: Session, expense: Expense) -> Expense | None:
    if expense.amount_cents is None or not expense.merchant:
        return None
    current_time = ensure_utc(expense.expense_time) or ensure_utc(expense.confirmed_at)
    if current_time is None:
        return None

    candidates = db.scalars(
        select(Expense)
        .where(Expense.id != expense.id)
        .where(Expense.tenant_id == expense.tenant_id)
        .where(Expense.status != "rejected")
        .where(Expense.amount_cents == expense.amount_cents)
        .where(Expense.merchant == expense.merchant)
        .order_by(Expense.created_at.asc())
    )
    for candidate in candidates:
        if _is_duplicate_ignored(db, expense.tenant_id, expense.id, candidate.id, "similar"):
            continue
        candidate_time = ensure_utc(candidate.expense_time) or ensure_utc(candidate.confirmed_at)
        if candidate_time is None:
            continue
        if abs(current_time - candidate_time) <= timedelta(hours=24):
            return candidate
    return None


def _is_duplicate_ignored(db: Session, tenant_id: str, expense_id: int, duplicate_of_id: int, kind: str) -> bool:
    left_id, right_id = _normalize_pair(expense_id, duplicate_of_id)
    return (
        db.scalar(
            select(DuplicateIgnore)
            .where(DuplicateIgnore.tenant_id == tenant_id)
            .where(DuplicateIgnore.expense_id == left_id)
            .where(DuplicateIgnore.duplicate_of_id == right_id)
            .where(DuplicateIgnore.kind == kind)
            .limit(1)
        )
        is not None
    )


def _remember_duplicate_ignore(db: Session, tenant_id: str, expense_id: int, duplicate_of_id: int, kind: str) -> None:
    left_id, right_id = _normalize_pair(expense_id, duplicate_of_id)
    db.execute(
        sqlite_insert(DuplicateIgnore)
        .values(
            tenant_id=tenant_id,
            expense_id=left_id,
            duplicate_of_id=right_id,
            kind=kind,
        )
        .on_conflict_do_nothing(
            index_elements=["tenant_id", "expense_id", "duplicate_of_id", "kind"]
        )
    )


def _normalize_pair(expense_id: int, duplicate_of_id: int) -> tuple[int, int]:
    return (expense_id, duplicate_of_id) if expense_id < duplicate_of_id else (duplicate_of_id, expense_id)


def list_suspected_duplicates(db: Session, tenant_id: str) -> list[Expense]:
    _clear_rejected_duplicate_targets(db, tenant_id=tenant_id)
    return list(
        db.scalars(
            select(Expense)
            .where(Expense.tenant_id == tenant_id)
            .where(Expense.duplicate_status == "suspected")
            .where(Expense.status != "rejected")
            .order_by(Expense.created_at.desc(), Expense.id.desc())
        )
    )


def clear_duplicate_references_to(db: Session, *, tenant_id: str, duplicate_of_id: int) -> int:
    result = db.execute(
        update(Expense)
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.status != "rejected")
        .where(Expense.duplicate_of_id == duplicate_of_id)
        .values(duplicate_status="none", duplicate_of_id=None, duplicate_reason=None)
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


def revalidate_duplicate_references_to(db: Session, *, tenant_id: str, duplicate_of_id: int) -> int:
    referenced = list(
        db.scalars(
            select(Expense)
            .where(Expense.tenant_id == tenant_id)
            .where(Expense.status != "rejected")
            .where(Expense.duplicate_of_id == duplicate_of_id)
            .order_by(Expense.id.asc())
        )
    )
    for expense in referenced:
        mark_duplicate_status(db, expense)
    return len(referenced)


def _clear_rejected_duplicate_targets(db: Session, *, tenant_id: str) -> int:
    rejected_targets = (
        select(Expense.id)
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.status == "rejected")
    )
    result = db.execute(
        update(Expense)
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.status != "rejected")
        .where(Expense.duplicate_of_id.in_(rejected_targets))
        .values(duplicate_status="none", duplicate_of_id=None, duplicate_reason=None)
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


def mark_not_duplicate(db: Session, expense: Expense) -> Expense:
    if expense.duplicate_of_id is not None:
        for kind in ACTIVE_DUPLICATE_IGNORE_KINDS:
            _remember_duplicate_ignore(db, expense.tenant_id, expense.id, expense.duplicate_of_id, kind)
    expense.duplicate_status = "none"
    expense.duplicate_of_id = None
    expense.duplicate_reason = None
    return expense


def _duplicate_kind(expense: Expense) -> str:
    reason = expense.duplicate_reason or ""
    if "感知" in reason:
        return "image_perceptual_hash"
    if "hash" in reason:
        return "image_hash"
    if "金额" in reason:
        return "similar"
    return "manual"
