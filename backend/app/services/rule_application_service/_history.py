"""List + rollback rule application batches."""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Expense, RuleApplicationBatch, RuleApplicationChange
from app.schemas._rules import RuleApplicationRollbackPreview, RuleRollbackSkippedItem
from app.services.category_service import normalize_category
from app.services.currency_binding_service import authorize_currency_metadata_write
from app.services.rule_application_service._common import (
    _changed_after_rule_application,
    _try_rollback_rule_change,
    normalize_rule_reason,
)
from app.services.time_service import now_utc


def list_rule_applications(
    db: Session,
    *,
    tenant_id: str,
    limit: int = 20,
) -> list[RuleApplicationBatch]:
    capped = max(1, min(int(limit or 20), 100))
    return list(
        db.scalars(
            ledger_scoped_select(RuleApplicationBatch, tenant_id)
            .order_by(RuleApplicationBatch.created_at.desc(), RuleApplicationBatch.id.desc())
            .limit(capped)
        )
    )


def rule_application_change_counts(
    db: Session, *, tenant_id: str, batch_ids: list[int],
) -> dict[int, dict[str, int]]:
    """Read retained outcomes together; no inference about why a change was skipped."""
    if not batch_ids:
        return {}
    rows = db.execute(
        ledger_scoped_select(RuleApplicationChange, tenant_id)
        .with_only_columns(RuleApplicationChange.batch_id, RuleApplicationChange.status, func.count())
        .where(RuleApplicationChange.batch_id.in_(batch_ids))
        .group_by(RuleApplicationChange.batch_id, RuleApplicationChange.status)
    )
    counts: dict[int, dict[str, int]] = {}
    for batch_id, status, count in rows:
        counts.setdefault(batch_id, {})[status] = count
    return counts


def _rollback_records(db: Session, tenant_id: str, batch_id: int):
    changes = list(db.scalars(ledger_scoped_select(RuleApplicationChange, tenant_id)
        .where(RuleApplicationChange.batch_id == batch_id).order_by(RuleApplicationChange.id.asc())))
    expense_ids = [change.expense_id for change in changes]
    expenses = {item.id: item for item in db.scalars(ledger_scoped_select(Expense, tenant_id)
        .where(Expense.id.in_(expense_ids)))} if expense_ids else {}
    return changes, expenses


def _rollback_skip_reason(change: RuleApplicationChange, expense: Expense | None) -> str | None:
    if change.status != "applied":
        return "already_rolled_back" if change.status == "rolled_back" else "already_skipped"
    if expense is None:
        return "expense_unavailable"
    if normalize_category(expense.category) != change.after_category or _changed_after_rule_application(expense, change):
        return "modified_after_application"
    return None


def preview_rule_application_rollback(db: Session, *, tenant_id: str, public_id: str) -> RuleApplicationRollbackPreview:
    batch = db.scalar(ledger_scoped_select(RuleApplicationBatch, tenant_id)
        .where(RuleApplicationBatch.public_id == public_id))
    if batch is None:
        raise AppError("rule_application_not_found", "规则应用批次不存在。", status_code=404)
    changes, expenses = _rollback_records(db, tenant_id, batch.id)
    skipped_items = []
    reasons: dict[str, int] = {}
    for change in changes:
        expense = expenses.get(change.expense_id)
        reason = _rollback_skip_reason(change, expense)
        if reason is None and batch.rolled_back_at is not None:
            reason = "batch_finished"
        if reason is not None:
            reasons[reason] = reasons.get(reason, 0) + 1
            skipped_items.append(RuleRollbackSkippedItem(expense_id=change.expense_id,
                merchant=expense.merchant if expense is not None else None, reason=reason))
    return RuleApplicationRollbackPreview(public_id=batch.public_id, original_count=batch.changed_count,
        eligible_count=len(changes) - len(skipped_items), skipped_count=len(skipped_items),
        reason_counts=reasons, skipped_items=skipped_items)


def rollback_rule_application(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    actor_account_id: int | None = None,
    actor_device_id: int | None = None,
    reason: str | None = None,
) -> tuple[RuleApplicationBatch, int, int]:
    reason = normalize_rule_reason(reason)
    authorize_currency_metadata_write(db)
    batch = db.scalar(
        ledger_scoped_select(RuleApplicationBatch, tenant_id).where(RuleApplicationBatch.public_id == public_id)
        .with_for_update()
    )
    if batch is None:
        raise AppError("rule_application_not_found", "规则应用批次不存在。", status_code=404)
    if batch.rolled_back_at is not None:
        outcomes = rule_application_change_counts(db, tenant_id=tenant_id, batch_ids=[batch.id]).get(batch.id, {})
        return batch, outcomes.get("rolled_back", 0), outcomes.get("skipped", 0)

    changes, expenses_by_id = _rollback_records(db, tenant_id, batch.id)
    now = now_utc()
    changed = 0
    skipped = 0
    for change in sorted(changes, key=lambda item: item.expense_id):
        if change.status != "applied":
            skipped += 1
            continue
        expense = expenses_by_id.get(change.expense_id)
        if _rollback_skip_reason(change, expense) is not None:
            change.status = "skipped"
            change.rolled_back_at = now
            skipped += 1
            continue
        if not _try_rollback_rule_change(
            db,
            tenant_id=tenant_id,
            expense=expense,
            change=change,
            now=now,
            actor_account_id=actor_account_id,
            actor_device_id=actor_device_id,
            reason=reason,
        ):
            change.status = "skipped"
            change.rolled_back_at = now
            skipped += 1
            continue
        change.status = "rolled_back"
        change.rolled_back_at = now
        changed += 1

    # Completed batches returned their original result above, under the same lock.
    if changed or skipped:
        if changed and skipped:
            batch.status = "rollback_partial"
        elif changed:
            batch.status = "rolled_back"
        else:
            batch.status = "rollback_skipped"
        batch.rolled_back_at = now
        batch.rollback_reason = reason
    db.commit()
    db.refresh(batch)
    return batch, changed, skipped
