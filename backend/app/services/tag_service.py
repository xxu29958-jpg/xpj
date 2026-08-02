from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ledger_scope import ledger_scoped_select
from app.models import Expense, ExpenseTag, Tag
from app.services.currency_binding_service import authorize_currency_metadata_write
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
    existing = db.scalar(ledger_scoped_select(Tag, tenant_id).where(Tag.key == key).limit(1))
    if existing is not None:
        # ADR-0043 契约 4: implicit re-creation colliding with a soft-deleted key
        # REVIVES that tag (so the unique key isn't violated and no duplicate is
        # made). The revive clears deleted_at AND bumps row_version, which CONSUMES
        # the original delete's undo token: that delete is no longer token-undoable
        # (undo step ② needs `deleted_at IS NOT NULL AND row_version == token` —
        # both now fail → 409). The delete snapshot is kept only so it age-purges on
        # its own created_at window (契约 6), NOT so the delete can still be undone.
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
    authorize_currency_metadata_write(db)
    names = parse_tags(value)
    expense.tags = format_tags(names)
    if expense.id is None:
        db.flush()

    existing_links = list(
        db.scalars(ledger_scoped_select(ExpenseTag, expense.tenant_id).where(ExpenseTag.expense_id == expense.id))
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
    has_links = db.scalar(ledger_scoped_select(ExpenseTag, tenant_id).limit(1))
    if has_links is not None:
        return

    expenses = list(db.scalars(ledger_scoped_select(Expense, tenant_id).where(Expense.tags.is_not(None))))
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
            ledger_scoped_select(ExpenseTag, expense.tenant_id).where(ExpenseTag.expense_id == expense.id)
        )
    }
    if not desired_keys and not link_tag_ids:
        return False
    current_keys: set[str] = set()
    if link_tag_ids:
        current_keys = {
            tag.key for tag in db.scalars(ledger_scoped_select(Tag, expense.tenant_id).where(Tag.id.in_(link_tag_ids)))
        }
    return desired_keys != current_keys


def _expense_tag_key_sets(db: Session, tenant_id: str, expense_ids: set[int]) -> dict[int, set[str]]:
    if not expense_ids:
        return {}
    rows = db.execute(
        select(ExpenseTag.expense_id, Tag.key)
        .join(Tag, Tag.id == ExpenseTag.tag_id)
        .where(ExpenseTag.tenant_id == tenant_id)
        .where(ExpenseTag.expense_id.in_(expense_ids))
        .where(Tag.tenant_id == tenant_id)
    )
    keys_by_expense_id: dict[int, set[str]] = {}
    for expense_id, key in rows:
        keys_by_expense_id.setdefault(int(expense_id), set()).add(str(key))
    return keys_by_expense_id


def _expense_tag_links_by_id(db: Session, tenant_id: str, expense_ids: set[int]) -> dict[int, list[ExpenseTag]]:
    if not expense_ids:
        return {}
    links = list(db.scalars(ledger_scoped_select(ExpenseTag, tenant_id).where(ExpenseTag.expense_id.in_(expense_ids))))
    links_by_expense_id: dict[int, list[ExpenseTag]] = {}
    for link in links:
        links_by_expense_id.setdefault(link.expense_id, []).append(link)
    return links_by_expense_id


def _tags_by_key_for_names(db: Session, tenant_id: str, names: list[str]) -> dict[str, Tag]:
    names_by_key: dict[str, str] = {}
    for name in names:
        key = tag_key(name)
        if key and key not in names_by_key:
            names_by_key[key] = clean_tag_name(name)
    if not names_by_key:
        return {}

    tags_by_key = {
        tag.key: tag for tag in db.scalars(ledger_scoped_select(Tag, tenant_id).where(Tag.key.in_(set(names_by_key))))
    }
    now = now_utc()
    created = False
    for key, name in names_by_key.items():
        tag = tags_by_key.get(key)
        if tag is None:
            tag = Tag(
                tenant_id=tenant_id,
                name=name,
                key=key,
                created_at=now,
                updated_at=now,
            )
            db.add(tag)
            tags_by_key[key] = tag
            created = True
            continue
        if tag.deleted_at is not None:
            tag.deleted_at = None
            tag.updated_at = now
            bump_row_version(tag)
    if created:
        db.flush()
    return tags_by_key


def _replace_expense_tag_links(
    db: Session,
    *,
    expense: Expense,
    target_tag_ids: set[int],
    existing_links: list[ExpenseTag],
) -> None:
    existing_by_tag_id = {link.tag_id: link for link in existing_links}
    created_at = now_utc()
    for tag_id in target_tag_ids:
        if tag_id not in existing_by_tag_id:
            db.add(
                ExpenseTag(
                    tenant_id=expense.tenant_id,
                    expense_id=expense.id,
                    tag_id=tag_id,
                    created_at=created_at,
                )
            )

    for link in existing_links:
        if link.tag_id not in target_tag_ids:
            db.delete(link)


def reconcile_expense_tag_mirror(db: Session, tenant_id: str, *, batch_size: int = 500) -> int:
    """Repair expenses whose ``tags`` string and ``expense_tags`` rows drifted.

    ADR-0043 slice A. The denormalised string is the source of truth (rule
    matcher / CSV export / DTO all read it); relation rows are rebuilt to match.
    Only expenses whose link key set differs from the string's are touched, and
    each fix bumps the expense ``row_version`` so a stale cross-surface PATCH
    can't silently revert the repair (契约 1 / [[feedback_row_version_bump_rule]]).
    Keyset-pages the mirror surface, reads each page's relation rows in bulk,
    then commits repairs per batch (§12); returns the number of expenses repaired.

    Idempotent — a second pass over already-consistent rows writes nothing.
    Closes the partial-drift gap :func:`backfill_expense_tags` can't (it only
    seeds links when *none* exist for the ledger).
    """
    fixed = 0
    last_id = 0
    page_size = max(1, batch_size)
    while True:
        expenses = list(
            db.scalars(
                ledger_scoped_select(Expense, tenant_id)
                .where(Expense.id > last_id)
                .order_by(Expense.id.asc())
                .limit(page_size)
            )
        )
        if not expenses:
            break
        last_id = expenses[-1].id
        expense_ids = {expense.id for expense in expenses}
        current_keys_by_id = _expense_tag_key_sets(db, tenant_id, expense_ids)

        drifted_expenses: list[Expense] = []
        desired_names_by_id: dict[int, list[str]] = {}
        for expense in expenses:
            names = parse_tags(expense.tags)
            desired_names_by_id[expense.id] = names
            desired_keys = {tag_key(name) for name in names}
            if desired_keys != current_keys_by_id.get(expense.id, set()):
                drifted_expenses.append(expense)
        if not drifted_expenses:
            db.expunge_all()
            continue

        # Each page commits independently, so transaction-local writer proof
        # must be acquired for every page that actually repairs Expense rows.
        authorize_currency_metadata_write(db)
        drifted_ids = {expense.id for expense in drifted_expenses}
        desired_names = [name for expense in drifted_expenses for name in desired_names_by_id[expense.id]]
        tags_by_key = _tags_by_key_for_names(db, tenant_id, desired_names)
        links_by_expense_id = _expense_tag_links_by_id(db, tenant_id, drifted_ids)

        for expense in drifted_expenses:
            names = desired_names_by_id[expense.id]
            expense.tags = format_tags(names)
            target_tag_ids = {tags_by_key[tag_key(name)].id for name in names}
            _replace_expense_tag_links(
                db,
                expense=expense,
                target_tag_ids=target_tag_ids,
                existing_links=links_by_expense_id.get(expense.id, []),
            )
            bump_row_version(expense)
        fixed += len(drifted_expenses)
        if drifted_expenses:
            db.commit()
        db.expunge_all()
    return fixed
