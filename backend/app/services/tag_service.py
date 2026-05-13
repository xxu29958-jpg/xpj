from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ledger_scope import ledger_scoped_select
from app.models import Expense, ExpenseTag, Tag
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
        .where(ExpenseTag.tenant_id == tenant_id)
        .distinct()
        .order_by(Tag.name.asc())
    )
    return [str(row[0]) for row in rows]


def _ensure_tag(db: Session, *, tenant_id: str, name: str) -> Tag:
    key = tag_key(name)
    existing = db.scalar(
        ledger_scoped_select(Tag, tenant_id).where(Tag.key == key).limit(1)
    )
    if existing is not None:
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
