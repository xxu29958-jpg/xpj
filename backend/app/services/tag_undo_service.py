"""ADR-0043 tag-mutation undo (split from tag_management_service for §1 size).

Single ordered transaction (契约 2): ① soft-claim the group (consumed_at,
rowcount=1 else 404) → ② atomically revive the soft-deleted source tag by its
public_id + the request's row_version token (stale/live/purged → 409, whole tx
rolls back) → ③ per-expense CAS replay (moved/deleted → skip, never overwrite)
→ ④ physically delete the group + items. Each phase is a helper so the
orchestrator reads as the contract's four steps.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete as sa_delete
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Expense, ExpenseTag, Tag, TagMutationUndoGroup, TagMutationUndoItem
from app.services._tag_results import TagUndoResult
from app.services.optimistic_concurrency import claim_row_with_token
from app.services.resource_audit import record_resource_action
from app.services.soft_delete_policy import (
    is_within_recycle_bin_window,
    is_within_undo_window,
)
from app.services.time_service import now_utc


def _claim_undo_group(
    db: Session,
    *,
    tenant_id: str,
    mutation_public_id: str,
    now: datetime,
    use_recycle_bin_window: bool,
) -> TagMutationUndoGroup:
    """① soft-claim the group via ``consumed_at`` (rowcount=1 guard → mutual
    exclusion vs a concurrent undo / purge). 404 if missing / consumed / past
    window."""
    group = db.scalar(
        ledger_scoped_select(TagMutationUndoGroup, tenant_id)
        .where(TagMutationUndoGroup.mutation_public_id == mutation_public_id)
        .where(TagMutationUndoGroup.consumed_at.is_(None))
        .limit(1)
    )
    window_check = (
        is_within_recycle_bin_window if use_recycle_bin_window else is_within_undo_window
    )
    if group is None or not window_check(group.created_at):
        raise AppError("tag_undo_not_found", status_code=404)
    claimed = db.execute(
        sa_update(TagMutationUndoGroup)
        .where(TagMutationUndoGroup.id == group.id)
        .where(TagMutationUndoGroup.tenant_id == tenant_id)
        .where(TagMutationUndoGroup.consumed_at.is_(None))
        .values(consumed_at=now)
    ).rowcount
    if claimed != 1:
        db.rollback()
        raise AppError("tag_undo_not_found", status_code=404)
    return group


def _revive_source_tag(
    db: Session, *, tenant_id: str, source_public_id: str, expected_row_version: int, now: datetime
) -> None:
    """② token-carrier guard: atomically clear ``deleted_at`` on the soft-deleted
    source tag iff it is still at the request's ``row_version`` token. A stale /
    already-live / purged token → rowcount=0 → 409 (whole tx rolls back)."""
    revived = db.execute(
        sa_update(Tag)
        .where(Tag.public_id == source_public_id)
        .where(Tag.tenant_id == tenant_id)
        .where(Tag.row_version == expected_row_version)
        .where(Tag.deleted_at.is_not(None))
        .values(deleted_at=None, updated_at=now, row_version=Tag.row_version + 1)
    ).rowcount
    if revived != 1:
        db.rollback()
        raise AppError("state_conflict", status_code=409)


def _restore_expense_links(db: Session, expense: Expense, original_tag_ids_csv: str) -> None:
    target_ids = {int(x) for x in original_tag_ids_csv.split(",") if x}
    # Only relink to tags that are currently LIVE (the source tag was just
    # revived; any other tag independently deleted since is skipped rather than
    # resurrecting a link to a soft-deleted/absent tag).
    live_ids = (
        set(
            db.scalars(
                ledger_scoped_select(Tag, expense.tenant_id)
                .where(Tag.id.in_(target_ids))
                .where(Tag.deleted_at.is_(None))
                .with_only_columns(Tag.id)
            )
        )
        if target_ids
        else set()
    )
    db.execute(
        sa_delete(ExpenseTag)
        .where(ExpenseTag.tenant_id == expense.tenant_id)
        .where(ExpenseTag.expense_id == expense.id)
    )
    now = now_utc()
    for tag_id in live_ids:
        db.add(
            ExpenseTag(
                tenant_id=expense.tenant_id,
                expense_id=expense.id,
                tag_id=tag_id,
                created_at=now,
            )
        )


def _replay_undo_items(db: Session, *, tenant_id: str, group_id: int) -> tuple[int, int]:
    """③ per-expense CAS replay. Restores each item's original string + link set
    iff the expense is still at the snapshot's CAS version; a moved / deleted
    expense is skipped (never overwritten). Returns (applied, skipped)."""
    items = list(
        db.scalars(
            ledger_scoped_select(TagMutationUndoItem, tenant_id).where(
                TagMutationUndoItem.group_id == group_id
            )
        )
    )
    # Batch-load every snapshotted expense up front (one query, not one per item)
    # so the replay loop holds no per-iteration SELECT.
    expenses_by_public_id: dict[str, Expense] = (
        {
            expense.public_id: expense
            for expense in db.scalars(
                ledger_scoped_select(Expense, tenant_id).where(
                    Expense.public_id.in_([item.expense_public_id for item in items])
                )
            )
        }
        if items
        else {}
    )
    applied = 0
    skipped = 0
    for item in items:
        expense = expenses_by_public_id.get(item.expense_public_id)
        if expense is None:
            skipped += 1
            continue
        rc = claim_row_with_token(
            db,
            Expense,
            pk_id=expense.id,
            tenant_id=tenant_id,
            expected_row_version=item.original_row_version,
            set_values={"tags": item.original_tags, "updated_at": now_utc()},
            synchronize_session=False,
        )
        if rc != 1:
            skipped += 1
            continue
        _restore_expense_links(db, expense, item.original_tag_ids)
        applied += 1
    return applied, skipped


def undo_tag_mutation(
    db: Session,
    *,
    tenant_id: str,
    mutation_public_id: str,
    expected_row_version: int,
    actor_account_id: int | None = None,
    use_recycle_bin_window: bool = False,
) -> TagUndoResult:
    """Undo a delete/merge in one ordered transaction (契约 2). Returns
    applied/skipped so partial undo is visible. A revived tag's delete is no
    longer token-undoable (契约 4) — step ② returns 409 once the token is stale."""
    now = now_utc()
    group = _claim_undo_group(
        db,
        tenant_id=tenant_id,
        mutation_public_id=mutation_public_id,
        now=now,
        use_recycle_bin_window=use_recycle_bin_window,
    )
    group_id = group.id
    source_public_id = group.source_tag_public_id

    _revive_source_tag(
        db,
        tenant_id=tenant_id,
        source_public_id=source_public_id,
        expected_row_version=expected_row_version,
        now=now,
    )
    applied, skipped = _replay_undo_items(db, tenant_id=tenant_id, group_id=group_id)

    # ④ physically delete the snapshot (items first — composite FK to group).
    db.execute(
        sa_delete(TagMutationUndoItem)
        .where(TagMutationUndoItem.tenant_id == tenant_id)
        .where(TagMutationUndoItem.group_id == group_id)
    )
    db.execute(
        sa_delete(TagMutationUndoGroup)
        .where(TagMutationUndoGroup.tenant_id == tenant_id)
        .where(TagMutationUndoGroup.id == group_id)
    )
    record_resource_action(
        db,
        ledger_id=tenant_id,
        action="undo",
        resource_type="tag",
        resource_public_id=source_public_id,
        actor_account_id=actor_account_id,
    )
    db.commit()
    return TagUndoResult(
        restored_tag_public_id=source_public_id,
        restored_tag_row_version=expected_row_version + 1,
        applied=applied,
        skipped=skipped,
    )
