from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session, aliased

from app.config import get_settings
from app.models import DuplicateIgnore, Expense, ExpenseOffsetFact
from app.services.duplicate_evidence import DuplicateCandidateScore, compare_duplicate_evidence, duplicate_reason
from app.services.optimistic_concurrency import bump_row_version
from app.services.time_service import now_utc

ACTIVE_DUPLICATE_IGNORE_KINDS = ("image_hash", "image_perceptual_hash", "similar")


def rank_duplicate_candidates(db: Session, *, expense: Expense,
        candidates: Iterable[Expense]) -> list[DuplicateCandidateScore]:
    # Runtime import keeps the append-only fact reader as the sole OCR authority
    # without introducing a package-initialization cycle with learning exports.
    from app.services.learning_service import read_ocr_facts

    rows = [row for row in candidates if row.id != expense.id and row.tenant_id == expense.tenant_id]
    ids = {row.id for row in rows} | {expense.id}
    excluded = set(db.scalars(select(ExpenseOffsetFact.expense_id).where(
        ExpenseOffsetFact.tenant_id == expense.tenant_id, ExpenseOffsetFact.expense_id.in_(ids),
        ExpenseOffsetFact.kind == "reversal", ExpenseOffsetFact.status == "active")))
    ignored = db.scalars(select(DuplicateIgnore).where(DuplicateIgnore.tenant_id == expense.tenant_id,
        or_(DuplicateIgnore.expense_id == expense.id, DuplicateIgnore.duplicate_of_id == expense.id)))
    excluded.update(row.duplicate_of_id if row.expense_id == expense.id else row.expense_id for row in ignored)
    if expense.id in excluded:
        return []
    facts = read_ocr_facts(db, tenant_id=expense.tenant_id, expenses=[expense, *rows])
    matches = [match for row in rows if row.id not in excluded
        if (match := compare_duplicate_evidence(expense, row,
            expense_fact=facts.get(expense.id), candidate_fact=facts.get(row.id))) is not None]
    return sorted(matches, key=lambda item: (-item.score, item.candidate_id))


def find_duplicate_candidates(db: Session, expense: Expense) -> list[DuplicateCandidateScore]:
    query = select(Expense).where(Expense.id != expense.id, Expense.tenant_id == expense.tenant_id,
        Expense.status != "rejected").order_by(Expense.created_at.desc(), Expense.id.desc())
    limit = get_settings().duplicate_phash_scan_limit
    # The bounded recent scan recalls visual/transaction-ID candidates. Indexed
    # exact-image and original-money queries also reach older matching records.
    rows = {row.id: row for row in db.scalars(query.limit(limit))}
    if expense.image_hash:
        rows |= {row.id: row for row in db.scalars(query.where(Expense.image_hash == expense.image_hash).limit(limit))}
    if expense.original_amount_minor is not None:
        rows |= {row.id: row for row in db.scalars(query.where(
            Expense.original_currency_code == expense.original_currency_code,
            Expense.original_amount_minor == expense.original_amount_minor).limit(limit))}
    elif expense.amount_cents is not None and expense.original_currency_code == expense.home_currency_code:
        rows |= {row.id: row for row in db.scalars(query.where(
            Expense.original_currency_code == expense.original_currency_code,
            Expense.amount_cents == expense.amount_cents).limit(limit))}
    # Review one small group at a time. An explicit pair exclusion recalls the
    # next group; it never excludes candidates omitted by this display bound.
    return rank_duplicate_candidates(db, expense=expense, candidates=rows.values())[:5]


def mark_duplicate_status(db: Session, expense: Expense) -> Expense:
    matches = find_duplicate_candidates(db, expense)
    expense.duplicate_status = "suspected" if matches else "none"
    expense.duplicate_of_id = matches[0].candidate_id if matches else None
    expense.duplicate_reason = duplicate_reason(matches[0]) if matches else None
    return expense


def _remember_duplicate_ignore(db: Session, tenant_id: str, expense_id: int, duplicate_of_id: int, kind: str) -> None:
    left_id, right_id = _normalize_pair(expense_id, duplicate_of_id)
    db.execute(
        postgresql_insert(DuplicateIgnore)
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
    active_target = aliased(Expense)
    return list(
        db.scalars(
            select(Expense)
            .join(active_target, active_target.id == Expense.duplicate_of_id)
            .where(Expense.tenant_id == tenant_id)
            .where(Expense.duplicate_status == "suspected")
            .where(Expense.status != "rejected")
            .where(active_target.tenant_id == tenant_id)
            .where(active_target.status != "rejected")
            .order_by(Expense.created_at.desc(), Expense.id.desc())
        )
    )


def clear_duplicate_references_to(db: Session, *, tenant_id: str, duplicate_of_id: int) -> int:
    now = now_utc()
    result = db.execute(
        update(Expense)
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.status != "rejected")
        .where(Expense.duplicate_of_id == duplicate_of_id)
        .values(
            duplicate_status="none",
            duplicate_of_id=None,
            duplicate_reason=None,
            updated_at=now,
            row_version=Expense.row_version + 1,
        )
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
        previous = (
            expense.duplicate_status,
            expense.duplicate_of_id,
            expense.duplicate_reason,
        )
        mark_duplicate_status(db, expense)
        current = (
            expense.duplicate_status,
            expense.duplicate_of_id,
            expense.duplicate_reason,
        )
        if current != previous:
            expense.updated_at = now_utc()
            bump_row_version(expense)
    return len(referenced)


def mark_not_duplicate(db: Session, expense: Expense) -> Expense:
    if expense.duplicate_of_id is not None:
        for kind in ACTIVE_DUPLICATE_IGNORE_KINDS:
            _remember_duplicate_ignore(db, expense.tenant_id, expense.id, expense.duplicate_of_id, kind)
    expense.duplicate_status = "none"
    expense.duplicate_of_id = None
    expense.duplicate_reason = None
    return expense
