"""Unique owner for projecting tag identity mutations onto Expense facts.

Tag management owns tag identity and undo groups. This module alone rewrites
the denormalised ``expenses.tags`` projection, its relation mirror, row-version
claim, and confirmed-fact revision as one command phase.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Expense, ExpenseTag, Tag, TagMutationUndoGroup, TagMutationUndoItem
from app.services.expense_revision_service import (
    prepare_correction_revision,
    record_prepared_correction_revision,
)
from app.services.optimistic_concurrency import claim_row_with_token
from app.services.tag_service import format_tags, replace_expense_tag_links
from app.services.time_service import now_utc


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


def expenses_linked_to_tag(
    db: Session, tenant_id: str, tag_id: int
) -> list[Expense]:
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


def _claim_expense_projection(
    db: Session,
    expense: Expense,
    *,
    tags: str | None,
    expected_row_version: int,
):
    prepared = prepare_correction_revision(db, expense)
    values = {"tags": tags, "updated_at": now_utc()}
    if prepared is not None:
        values["fact_revision"] = Expense.fact_revision + 1
    claimed = claim_row_with_token(
        db,
        Expense,
        pk_id=expense.id,
        tenant_id=expense.tenant_id,
        expected_row_version=expected_row_version,
        set_values=values,
        synchronize_session=False,
    )
    return prepared, claimed


def _append_projection_revision(
    db: Session,
    expense: Expense,
    prepared,
    *,
    reason: str,
    actor_account_id: int | None,
    actor_device_id: int | None,
) -> None:
    if prepared is None:
        return
    db.flush()
    db.refresh(expense)
    record_prepared_correction_revision(
        db,
        expense,
        prepared,
        reason=reason,
        actor_account_id=actor_account_id,
        actor_device_id=actor_device_id,
    )


def rewrite_expenses_for_tag_rename(
    db: Session,
    *,
    tenant_id: str,
    tag_id: int,
    reason: str,
    actor_account_id: int | None,
    actor_device_id: int | None,
) -> None:
    for expense in expenses_linked_to_tag(db, tenant_id, tag_id):
        tags = format_tags([tag.name for tag in _linked_tags(db, tenant_id, expense.id)])
        prepared, claimed = _claim_expense_projection(
            db, expense, tags=tags, expected_row_version=expense.row_version
        )
        if claimed != 1:
            db.rollback()
            raise AppError("state_conflict", status_code=409)
        _append_projection_revision(
            db,
            expense,
            prepared,
            reason=reason,
            actor_account_id=actor_account_id,
            actor_device_id=actor_device_id,
        )


def rewrite_expense_for_tag_change(
    db: Session,
    *,
    group: TagMutationUndoGroup,
    expense: Expense,
    removed_tag_id: int,
    replacement_tag: Tag | None,
    reason: str,
    actor_account_id: int | None,
    actor_device_id: int | None,
) -> None:
    current_tags = _linked_tags(db, expense.tenant_id, expense.id)
    new_tags = [tag for tag in current_tags if tag.id != removed_tag_id]
    if replacement_tag is not None and all(tag.id != replacement_tag.id for tag in new_tags):
        new_tags.append(replacement_tag)
    db.add(
        TagMutationUndoItem(
            tenant_id=expense.tenant_id,
            group_id=group.id,
            expense_public_id=expense.public_id,
            original_tags=expense.tags,
            original_tag_ids=",".join(str(tag.id) for tag in current_tags),
            original_row_version=expense.row_version + 1,
            created_at=now_utc(),
        )
    )
    replace_expense_tag_links(
        db,
        expense=expense,
        target_tag_ids={tag.id for tag in new_tags},
    )
    prepared, claimed = _claim_expense_projection(
        db,
        expense,
        tags=format_tags([tag.name for tag in new_tags]),
        expected_row_version=expense.row_version,
    )
    if claimed != 1:
        raise AppError("state_conflict", status_code=409)
    _append_projection_revision(
        db,
        expense,
        prepared,
        reason=reason,
        actor_account_id=actor_account_id,
        actor_device_id=actor_device_id,
    )


def _restore_expense_links(
    db: Session, expense: Expense, original_tag_ids_csv: str
) -> None:
    target_ids = {int(value) for value in original_tag_ids_csv.split(",") if value}
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
    replace_expense_tag_links(db, expense=expense, target_tag_ids=live_ids)


def replay_undo_items(
    db: Session,
    *,
    tenant_id: str,
    group_id: int,
    actor_account_id: int | None,
    actor_device_id: int | None,
) -> tuple[int, int]:
    items = list(
        db.scalars(
            ledger_scoped_select(TagMutationUndoItem, tenant_id).where(
                TagMutationUndoItem.group_id == group_id
            )
        )
    )
    expenses = (
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
    for item in items:
        expense = expenses.get(item.expense_public_id)
        if expense is None:
            continue
        prepared, claimed = _claim_expense_projection(
            db,
            expense,
            tags=item.original_tags,
            expected_row_version=item.original_row_version,
        )
        if claimed != 1:
            continue
        _restore_expense_links(db, expense, item.original_tag_ids)
        _append_projection_revision(
            db,
            expense,
            prepared,
            reason="撤销标签删除或合并",
            actor_account_id=actor_account_id,
            actor_device_id=actor_device_id,
        )
        applied += 1
    return applied, len(items) - applied
