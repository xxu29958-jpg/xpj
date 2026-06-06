"""ADR-0043 tag management: online-only rename / delete / merge / undo.

The denormalised ``expenses.tags`` string is the source of truth that the rule
matcher / CSV export / DTO read; ``tags`` + ``expense_tags`` are the relation
mirror. Management ops mutate the tag identity/links first, then rebuild every
affected expense's string FROM its links and bump that expense's ``row_version``
(契约 1) so a stale cross-surface PATCH can't silently revert the change. delete
and merge soft-delete the source tag and write one ``tag_mutation_undo_groups``
row + N ``tag_mutation_undo_items`` rows in the SAME transaction; rename is
self-inverse (rename back) and writes no snapshot. undo is a single ordered
transaction (契约 2). Precedent: ``merchant_alias_service`` (OCC + soft-delete +
undo); the cascade + snapshot + token-carrier undo are tag-specific.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Expense, ExpenseTag, Tag, TagMutationUndoGroup, TagMutationUndoItem
from app.services.optimistic_concurrency import claim_row_with_token
from app.services.resource_audit import record_resource_action
from app.services.tag_service import clean_tag_name, format_tags, tag_key
from app.services.time_service import now_utc


@dataclass(frozen=True)
class TagUsageItem:
    public_id: str
    name: str
    usage_count: int
    row_version: int


@dataclass(frozen=True)
class TagMutationResult:
    """Result of a delete/merge. ``source_tag_row_version`` is the undo token —
    the soft-deleted source tag's new ``row_version`` (契约 2 step ②)."""

    mutation_public_id: str
    op: str
    source_tag_public_id: str
    source_tag_row_version: int
    target_tag_public_id: str | None
    target_tag_row_version: int | None
    affected_expense_count: int


@dataclass(frozen=True)
class TagUndoResult:
    restored_tag_public_id: str
    restored_tag_row_version: int
    applied: int
    skipped: int


# --------------------------------------------------------------------------- #
# Read helpers
# --------------------------------------------------------------------------- #
def _live_tag(db: Session, tenant_id: str, public_id: str) -> Tag | None:
    return db.scalar(
        ledger_scoped_select(Tag, tenant_id)
        .where(Tag.public_id == public_id)
        .where(Tag.deleted_at.is_(None))
        .limit(1)
    )


def _require_live_tag(db: Session, tenant_id: str, public_id: str) -> Tag:
    tag = _live_tag(db, tenant_id, public_id)
    if tag is None:
        raise AppError("tag_not_found", status_code=404)
    return tag


def _tag_by_key_any_state(db: Session, tenant_id: str, key: str) -> Tag | None:
    """Tag by key INCLUDING soft-deleted (the unique (tenant,key) constraint
    spans soft-deleted rows, so a soft-deleted key stays reserved)."""
    return db.scalar(
        ledger_scoped_select(Tag, tenant_id).where(Tag.key == key).limit(1)
    )


def list_tags_with_usage(db: Session, tenant_id: str) -> list[TagUsageItem]:
    """Live tags + their expense usage count (count desc, then name). Orphans
    (usage 0, e.g. left behind by ``set_expense_tags`` dropping the last link)
    surface with usage_count=0 so the management UI can clean them up."""
    rows = db.execute(
        select(Tag.public_id, Tag.name, Tag.row_version, func.count(ExpenseTag.id))
        .outerjoin(
            ExpenseTag,
            (ExpenseTag.tag_id == Tag.id) & (ExpenseTag.tenant_id == tenant_id),
        )
        .where(Tag.tenant_id == tenant_id)
        .where(Tag.deleted_at.is_(None))
        .group_by(Tag.public_id, Tag.name, Tag.row_version)
        .order_by(func.count(ExpenseTag.id).desc(), Tag.name.asc())
    )
    return [
        TagUsageItem(public_id=str(pid), name=str(name), usage_count=int(count or 0), row_version=int(rv))
        for pid, name, rv, count in rows
    ]


# --------------------------------------------------------------------------- #
# Mirror helpers
# --------------------------------------------------------------------------- #
def _linked_tags(db: Session, tenant_id: str, expense_id: int) -> list[Tag]:
    return list(
        db.scalars(
            select(Tag)
            .join(ExpenseTag, ExpenseTag.tag_id == Tag.id)
            .where(ExpenseTag.tenant_id == tenant_id)
            .where(ExpenseTag.expense_id == expense_id)
            .where(Tag.tenant_id == tenant_id)
            .order_by(ExpenseTag.id.asc())
        )
    )


def _expenses_linked_to_tag(db: Session, tenant_id: str, tag_id: int) -> list[Expense]:
    return list(
        db.scalars(
            select(Expense)
            .join(ExpenseTag, ExpenseTag.expense_id == Expense.id)
            .where(ExpenseTag.tenant_id == tenant_id)
            .where(ExpenseTag.tag_id == tag_id)
            .where(Expense.tenant_id == tenant_id)
            .order_by(Expense.id.asc())
        )
    )


def _rewrite_expense_for_tag_change(
    db: Session,
    *,
    group: TagMutationUndoGroup,
    expense: Expense,
    removed_tag_id: int,
    replacement_tag: Tag | None,
) -> None:
    """Snapshot the expense, retag it (drop ``removed_tag_id``; for merge add
    ``replacement_tag``), rebuild its ``tags`` string from the new link set, and
    bump its ``row_version`` via an OCC claim — all in the caller's transaction.

    Raises ``state_conflict`` if a concurrent writer bumped the expense between
    our read and the claim (rare; the whole forward op then rolls back)."""
    current_tags = _linked_tags(db, expense.tenant_id, expense.id)
    original_tag_ids = [t.id for t in current_tags]
    original_tags_str = expense.tags
    pre_version = expense.row_version

    new_tags: list[Tag] = [t for t in current_tags if t.id != removed_tag_id]
    if replacement_tag is not None and all(t.id != replacement_tag.id for t in new_tags):
        new_tags.append(replacement_tag)
    new_string = format_tags([t.name for t in new_tags])

    # Snapshot BEFORE mutating. cas token = the version the forward op leaves the
    # expense at (pre_version + 1) — undo restores only if the expense is still
    # there (no edit since).
    db.add(
        TagMutationUndoItem(
            tenant_id=expense.tenant_id,
            group_id=group.id,
            expense_public_id=expense.public_id,
            original_tags=original_tags_str,
            original_tag_ids=",".join(str(i) for i in original_tag_ids),
            original_row_version=pre_version + 1,
            created_at=now_utc(),
        )
    )

    # Relation rows: drop the source link; for merge add the target link unless
    # it already exists (dedup against uq_expense_tags_tenant_expense_tag).
    db.execute(
        sa_delete(ExpenseTag)
        .where(ExpenseTag.tenant_id == expense.tenant_id)
        .where(ExpenseTag.expense_id == expense.id)
        .where(ExpenseTag.tag_id == removed_tag_id)
    )
    if replacement_tag is not None and all(t.id != replacement_tag.id for t in current_tags):
        db.add(
            ExpenseTag(
                tenant_id=expense.tenant_id,
                expense_id=expense.id,
                tag_id=replacement_tag.id,
                created_at=now_utc(),
            )
        )

    rowcount = claim_row_with_token(
        db,
        Expense,
        pk_id=expense.id,
        tenant_id=expense.tenant_id,
        expected_row_version=pre_version,
        set_values={"tags": new_string, "updated_at": now_utc()},
        synchronize_session=False,
    )
    if rowcount != 1:
        raise AppError("state_conflict", status_code=409)


def _disambiguate_tag_claim(db: Session, tenant_id: str, public_id: str) -> AppError:
    """After a failed Tag OCC claim: 404 if no longer live, else 409."""
    db.rollback()
    if _live_tag(db, tenant_id, public_id) is None:
        return AppError("tag_not_found", status_code=404)
    return AppError("state_conflict", status_code=409)


def _claim_merge_pair(
    db: Session,
    *,
    tenant_id: str,
    source: Tag,
    target: Tag,
    source_row_version: int,
    target_row_version: int,
) -> None:
    """Atomically soft-delete source A (keeps its tag_id; revivable via undo) and
    bump target B (stays live; its link set changed so a stale B PATCH must 409).
    Either token stale → 409, rolling the pair back. A is the soft-deleted one,
    so the undo token is A's (契约 2/3)."""
    now = now_utc()
    if (
        claim_row_with_token(
            db,
            Tag,
            pk_id=source.id,
            tenant_id=tenant_id,
            expected_row_version=source_row_version,
            set_values={"deleted_at": now, "updated_at": now},
            synchronize_session=False,
        )
        != 1
    ):
        raise _disambiguate_tag_claim(db, tenant_id, source.public_id)
    if (
        claim_row_with_token(
            db,
            Tag,
            pk_id=target.id,
            tenant_id=tenant_id,
            expected_row_version=target_row_version,
            set_values={"updated_at": now},
            synchronize_session=False,
        )
        != 1
    ):
        raise _disambiguate_tag_claim(db, tenant_id, target.public_id)


# --------------------------------------------------------------------------- #
# Mutations
# --------------------------------------------------------------------------- #
def rename_tag(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    expected_row_version: int,
    name: str,
) -> Tag:
    """Self-inverse rename (no snapshot — undo by renaming back). Rewrites the
    denormalised string on every linked expense (the string carries the NAME)
    and bumps them. Colliding with another key (incl. soft-deleted) → 409
    ``tag_conflict`` carrying the existing tag's public_id + row_version so the
    client can offer a merge (契约 5)."""
    tag = _require_live_tag(db, tenant_id, public_id)
    new_name = clean_tag_name(name)
    new_key = tag_key(new_name)
    if not new_key:
        raise AppError("invalid_request", "标签名不能为空。", status_code=422)

    if new_key != tag.key:
        clash = _tag_by_key_any_state(db, tenant_id, new_key)
        if clash is not None and clash.id != tag.id:
            raise AppError(
                "tag_conflict",
                status_code=409,
                details={
                    "conflict_tag_public_id": clash.public_id,
                    "conflict_tag_row_version": int(clash.row_version),
                },
            )

    rowcount = claim_row_with_token(
        db,
        Tag,
        pk_id=tag.id,
        tenant_id=tenant_id,
        expected_row_version=expected_row_version,
        set_values={"name": new_name, "key": new_key, "updated_at": now_utc()},
        synchronize_session=False,
    )
    if rowcount != 1:
        raise _disambiguate_tag_claim(db, tenant_id, public_id)

    # claim_row_with_token issued a Core UPDATE (synchronize_session=False) so the
    # identity-mapped Tag still carries the OLD name; expire it before rebuilding
    # the mirror or _linked_tags would re-emit the stale name.
    db.expire_all()

    # The string on every linked expense now shows the old name — rebuild + bump.
    for expense in _expenses_linked_to_tag(db, tenant_id, tag.id):
        names = [t.name for t in _linked_tags(db, tenant_id, expense.id)]
        pre = expense.row_version
        claimed = claim_row_with_token(
            db,
            Expense,
            pk_id=expense.id,
            tenant_id=tenant_id,
            expected_row_version=pre,
            set_values={"tags": format_tags(names), "updated_at": now_utc()},
            synchronize_session=False,
        )
        if claimed != 1:
            db.rollback()
            raise AppError("state_conflict", status_code=409)

    db.commit()
    db.expire_all()
    return _require_live_tag(db, tenant_id, public_id)


def delete_tag(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    expected_row_version: int,
    actor_account_id: int | None = None,
) -> TagMutationResult:
    """Soft-delete the tag, untag every linked expense (rebuild string + bump),
    and write the undo snapshot — one transaction (契约 1). An orphan tag (no
    links) still writes a group row (undo anchor) with zero items."""
    tag = _require_live_tag(db, tenant_id, public_id)

    rowcount = claim_row_with_token(
        db,
        Tag,
        pk_id=tag.id,
        tenant_id=tenant_id,
        expected_row_version=expected_row_version,
        set_values={"deleted_at": now_utc(), "updated_at": now_utc()},
        synchronize_session=False,
    )
    if rowcount != 1:
        raise _disambiguate_tag_claim(db, tenant_id, public_id)

    group = TagMutationUndoGroup(
        tenant_id=tenant_id,
        op="delete",
        source_tag_public_id=tag.public_id,
        source_tag_name=tag.name,
        created_at=now_utc(),
    )
    db.add(group)
    db.flush()

    affected = 0
    for expense in _expenses_linked_to_tag(db, tenant_id, tag.id):
        _rewrite_expense_for_tag_change(
            db, group=group, expense=expense, removed_tag_id=tag.id, replacement_tag=None
        )
        affected += 1

    record_resource_action(
        db,
        ledger_id=tenant_id,
        action="delete",
        resource_type="tag",
        resource_public_id=tag.public_id,
        actor_account_id=actor_account_id,
    )
    db.commit()
    return TagMutationResult(
        mutation_public_id=group.mutation_public_id,
        op="delete",
        source_tag_public_id=tag.public_id,
        source_tag_row_version=expected_row_version + 1,
        target_tag_public_id=None,
        target_tag_row_version=None,
        affected_expense_count=affected,
    )


def merge_tags(
    db: Session,
    *,
    tenant_id: str,
    source_public_id: str,
    source_row_version: int,
    target_public_id: str,
    target_row_version: int,
    actor_account_id: int | None = None,
) -> TagMutationResult:
    """Merge source A into target B: soft-delete A (keep its tag_id stable),
    move A's links to B (dedup), rebuild + bump each affected expense, write the
    undo snapshot — one transaction. Both tokens are checked: either stale → 409
    (the undo token is A's, since A is the soft-deleted one, 契约 2/3)."""
    source = _require_live_tag(db, tenant_id, source_public_id)
    target = _require_live_tag(db, tenant_id, target_public_id)
    if source.id == target.id:
        raise AppError("invalid_request", "不能把标签合并到自身。", status_code=422)

    source_id = source.id
    _claim_merge_pair(
        db,
        tenant_id=tenant_id,
        source=source,
        target=target,
        source_row_version=source_row_version,
        target_row_version=target_row_version,
    )

    group = TagMutationUndoGroup(
        tenant_id=tenant_id,
        op="merge",
        source_tag_public_id=source.public_id,
        source_tag_name=source.name,
        target_tag_public_id=target.public_id,
        target_tag_name=target.name,
        created_at=now_utc(),
    )
    db.add(group)
    db.flush()

    affected = 0
    for expense in _expenses_linked_to_tag(db, tenant_id, source_id):
        _rewrite_expense_for_tag_change(
            db, group=group, expense=expense, removed_tag_id=source_id, replacement_tag=target
        )
        affected += 1

    record_resource_action(
        db,
        ledger_id=tenant_id,
        action="merge",
        resource_type="tag",
        resource_public_id=source.public_id,
        actor_account_id=actor_account_id,
    )
    db.commit()
    return TagMutationResult(
        mutation_public_id=group.mutation_public_id,
        op="merge",
        source_tag_public_id=source_public_id,
        source_tag_row_version=source_row_version + 1,
        target_tag_public_id=target_public_id,
        target_tag_row_version=target_row_version + 1,
        affected_expense_count=affected,
    )
