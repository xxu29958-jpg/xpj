from __future__ import annotations

from datetime import timedelta

from sqlalchemy import and_, or_
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DuplicateIgnore, Expense
from app.services.time_service import ensure_utc


def mark_duplicate_status(db: Session, expense: Expense) -> Expense:
    duplicate = _find_same_image(db, expense)
    if duplicate is not None:
        expense.duplicate_status = "suspected"
        expense.duplicate_of_id = duplicate.id
        expense.duplicate_reason = "图片 hash 完全一致，可能是重复截图。"
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
        .where(Expense.status != "rejected")
        .where(Expense.image_hash == expense.image_hash)
        .order_by(Expense.created_at.asc())
    )
    for candidate in candidates:
        if not _is_duplicate_ignored(db, expense.id, candidate.id, "image_hash"):
            return candidate
    return None


def _find_similar_expense(db: Session, expense: Expense) -> Expense | None:
    if expense.amount_cents is None or not expense.merchant:
        return None
    current_time = ensure_utc(expense.expense_time) or ensure_utc(expense.confirmed_at)
    if current_time is None:
        return None

    candidates = db.scalars(
        select(Expense)
        .where(Expense.id != expense.id)
        .where(Expense.status != "rejected")
        .where(Expense.amount_cents == expense.amount_cents)
        .where(Expense.merchant == expense.merchant)
        .order_by(Expense.created_at.asc())
    )
    for candidate in candidates:
        if _is_duplicate_ignored(db, expense.id, candidate.id, "similar"):
            continue
        candidate_time = ensure_utc(candidate.expense_time) or ensure_utc(candidate.confirmed_at)
        if candidate_time is None:
            continue
        if abs(current_time - candidate_time) <= timedelta(hours=24):
            return candidate
    return None


def _is_duplicate_ignored(db: Session, expense_id: int, duplicate_of_id: int, kind: str) -> bool:
    left_id, right_id = _normalize_pair(expense_id, duplicate_of_id)
    return (
        db.scalar(
            select(DuplicateIgnore)
            .where(DuplicateIgnore.expense_id == left_id)
            .where(DuplicateIgnore.duplicate_of_id == right_id)
            .where(DuplicateIgnore.kind == kind)
            .limit(1)
        )
        is not None
    )


def _remember_duplicate_ignore(db: Session, expense_id: int, duplicate_of_id: int, kind: str) -> None:
    left_id, right_id = _normalize_pair(expense_id, duplicate_of_id)
    exists = db.scalar(
        select(DuplicateIgnore)
        .where(
            or_(
                and_(
                    DuplicateIgnore.expense_id == left_id,
                    DuplicateIgnore.duplicate_of_id == right_id,
                    DuplicateIgnore.kind == kind,
                ),
                and_(
                    DuplicateIgnore.expense_id == right_id,
                    DuplicateIgnore.duplicate_of_id == left_id,
                    DuplicateIgnore.kind == kind,
                ),
            )
        )
        .limit(1)
    )
    if exists is None:
        db.add(DuplicateIgnore(expense_id=left_id, duplicate_of_id=right_id, kind=kind))


def _normalize_pair(expense_id: int, duplicate_of_id: int) -> tuple[int, int]:
    return (expense_id, duplicate_of_id) if expense_id < duplicate_of_id else (duplicate_of_id, expense_id)


def list_suspected_duplicates(db: Session) -> list[Expense]:
    return list(
        db.scalars(
            select(Expense)
            .where(Expense.duplicate_status == "suspected")
            .where(Expense.status != "rejected")
            .order_by(Expense.created_at.desc(), Expense.id.desc())
        )
    )


def mark_not_duplicate(db: Session, expense: Expense) -> Expense:
    if expense.duplicate_of_id is not None:
        _remember_duplicate_ignore(db, expense.id, expense.duplicate_of_id, _duplicate_kind(expense))
    expense.duplicate_status = "none"
    expense.duplicate_of_id = None
    expense.duplicate_reason = None
    return expense


def _duplicate_kind(expense: Expense) -> str:
    reason = expense.duplicate_reason or ""
    if "hash" in reason:
        return "image_hash"
    if "金额" in reason:
        return "similar"
    return "manual"
