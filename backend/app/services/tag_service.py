from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ledger_scope import ledger_scoped_select
from app.models import Expense, ExpenseTag, Tag
from app.services.optimistic_concurrency import bump_row_version
from app.services.time_service import now_utc

TAG_SEPARATOR_RE = re.compile(r"[,，;；\n]+")
TAG_SPACE_RE = re.compile(r"\s+")


def clean_tag_name(value: str | None) -> str:
    if value is None:
        return ""
    return TAG_SPACE_RE.sub(" ", value.strip()).strip()


def tag_key(value: str | None) -> str:
    return clean_tag_name(value).casefold()


def parse_tags(value: str | None) -> list[str]:
    if not value:
        return []
    seen: set[str] = set()
    tags: list[str] = []
    for raw in TAG_SEPARATOR_RE.split(value):
        name = clean_tag_name(raw)
        key = tag_key(name)
        if not key or key in seen:
            continue
        seen.add(key)
        tags.append(name)
    return tags


def format_tags(tags: list[str]) -> str | None:
    cleaned = parse_tags(",".join(tags))
    return ", ".join(cleaned) if cleaned else None


def normalize_tags(value: str | None) -> str | None:
    return format_tags(parse_tags(value))


def list_tags(db: Session, tenant_id: str) -> list[str]:
    rows = db.execute(
        select(Tag.name)
        .join(ExpenseTag, ExpenseTag.tag_id == Tag.id)
        .where(Tag.tenant_id == tenant_id)
        .where(Tag.deleted_at.is_(None))  # ADR-0043: never surface soft-deleted tags
        .where(ExpenseTag.tenant_id == tenant_id)
        .distinct()
        .order_by(Tag.name.asc())
    )
    return [str(row[0]) for row in rows]


def _ensure_tag(db: Session, *, tenant_id: str, name: str) -> Tag:
    key = tag_key(name)
    # The (tenant_id, key) unique constraint spans soft-deleted rows, so this
    # returns at most one tag for the key — live OR soft-deleted.
    existing = db.scalar(
        ledger_scoped_select(Tag, tenant_id).where(Tag.key == key).limit(1)
    )
    if existing is not None:
        # ADR-0043 契约 4: implicit re-creation colliding with a soft-deleted key
        # REVIVES that tag (so the unique key isn't violated and no duplicate is
        # made) but keeps its delete snapshot — the original delete stays undoable
        # (the snapshot purges on its own age, not on this revival, 契约 6).
        if existing.deleted_at is not None:
            existing.deleted_at = None
            existing.updated_at = now_utc()
            bump_row_version(existing)
            db.flush()
        return existing

    now = now_utc()
    item = Tag(
        tenant_id=tenant_id,
        name=clean_tag_name(name),
        key=key,
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    db.flush()
    return item


def set_expense_tags(db: Session, expense: Expense, value: str | None) -> None:
    names = parse_tags(value)
    expense.tags = format_tags(names)
    if expense.id is None:
        db.flush()

    existing_links = list(
        db.scalars(
            ledger_scoped_select(ExpenseTag, expense.tenant_id).where(
                ExpenseTag.expense_id == expense.id
            )
        )
    )
    existing_by_tag_id = {link.tag_id: link for link in existing_links}
    target_tag_ids: set[int] = set()
    for name in names:
        tag = _ensure_tag(db, tenant_id=expense.tenant_id, name=name)
        target_tag_ids.add(tag.id)
        if tag.id not in existing_by_tag_id:
            db.add(
                ExpenseTag(
                    tenant_id=expense.tenant_id,
                    expense_id=expense.id,
                    tag_id=tag.id,
                    created_at=now_utc(),
                )
            )

    for link in existing_links:
        if link.tag_id not in target_tag_ids:
            db.delete(link)


def sync_expense_tags(db: Session, expense: Expense) -> None:
    set_expense_tags(db, expense, expense.tags)


def backfill_expense_tags(db: Session, tenant_id: str) -> None:
    has_links = db.scalar(
        ledger_scoped_select(ExpenseTag, tenant_id).limit(1)
    )
    if has_links is not None:
        return

    expenses = list(
        db.scalars(
            ledger_scoped_select(Expense, tenant_id).where(Expense.tags.is_not(None))
        )
    )
    for expense in expenses:
        set_expense_tags(db, expense, expense.tags)
    if expenses:
        db.commit()


def _expense_tag_mirror_drifted(db: Session, expense: Expense) -> bool:
    """True if the expense's ``tags`` string and ``expense_tags`` links disagree.

    Compares the two as *key sets* (casefold), so case/order/whitespace-only
    string differences that the relation already represents correctly are not
    treated as drift (and so don't trigger a needless ``row_version`` bump).
    """
    desired_keys = {tag_key(name) for name in parse_tags(expense.tags)}
    link_tag_ids = {
        link.tag_id
        for link in db.scalars(
            ledger_scoped_select(ExpenseTag, expense.tenant_id).where(
                ExpenseTag.expense_id == expense.id
            )
        )
    }
    if not desired_keys and not link_tag_ids:
        return False
    current_keys: set[str] = set()
    if link_tag_ids:
        current_keys = {
            tag.key
            for tag in db.scalars(
                ledger_scoped_select(Tag, expense.tenant_id).where(Tag.id.in_(link_tag_ids))
            )
        }
    return desired_keys != current_keys


def reconcile_expense_tag_mirror(db: Session, tenant_id: str, *, batch_size: int = 500) -> int:
    """Repair expenses whose ``tags`` string and ``expense_tags`` rows drifted.

    ADR-0043 slice A. The denormalised string is the source of truth (rule
    matcher / CSV export / DTO all read it); relation rows are rebuilt to match.
    Only expenses whose link key set differs from the string's are touched, and
    each fix bumps the expense ``row_version`` so a stale cross-surface PATCH
    can't silently revert the repair (契约 1 / [[feedback_row_version_bump_rule]]).
    Paged + committed per batch (§12); returns the number of expenses repaired.

    Idempotent — a second pass over already-consistent rows writes nothing.
    Closes the partial-drift gap :func:`backfill_expense_tags` can't (it only
    seeds links when *none* exist for the ledger).
    """
    fixed = 0
    last_id = 0
    while True:
        expenses = list(
            db.scalars(
                ledger_scoped_select(Expense, tenant_id)
                .where(Expense.id > last_id)
                .order_by(Expense.id.asc())
                .limit(batch_size)
            )
        )
        if not expenses:
            break
        batch_fixed = 0
        for expense in expenses:
            last_id = expense.id
            if _expense_tag_mirror_drifted(db, expense):
                set_expense_tags(db, expense, expense.tags)
                bump_row_version(expense)
                batch_fixed += 1
        if batch_fixed:
            db.commit()
        db.expunge_all()
        fixed += batch_fixed
    return fixed
