"""List + rollback rule application batches."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Expense, RuleApplicationBatch, RuleApplicationChange
from app.services.category_service import normalize_category
from app.services.rule_application_service._common import (
    _changed_after_rule_application,
    _try_rollback_rule_change,
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


def rollback_rule_application(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
) -> tuple[RuleApplicationBatch, int, int]:
    batch = db.scalar(
        ledger_scoped_select(RuleApplicationBatch, tenant_id).where(
            RuleApplicationBatch.public_id == public_id
        )
    )
    if batch is None:
        raise AppError("rule_application_not_found", "规则应用批次不存在。", status_code=404)

    changes = list(
        db.scalars(
            ledger_scoped_select(RuleApplicationChange, tenant_id)
            .where(RuleApplicationChange.batch_id == batch.id)
            .order_by(RuleApplicationChange.id.asc())
        )
    )
    now = now_utc()
    changed = 0
    skipped = 0
    for change in changes:
        if change.status != "applied":
            skipped += 1
            continue
        expense = db.scalar(
            ledger_scoped_select(Expense, tenant_id).where(Expense.id == change.expense_id)
        )
        if (
            expense is None
            or normalize_category(expense.category) != change.after_category
            or _changed_after_rule_application(expense, change)
        ):
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
        ):
            change.status = "skipped"
            change.rolled_back_at = now
            skipped += 1
            continue
        change.status = "rolled_back"
        change.rolled_back_at = now
        changed += 1

    if changed > 0 and skipped > 0 and batch.status != "rollback_partial":
        batch.status = "rollback_partial"
        batch.rolled_back_at = now
    elif changed > 0 and batch.status != "rolled_back":
        batch.status = "rolled_back"
        batch.rolled_back_at = now
    elif changed == 0 and skipped > 0 and batch.status != "rolled_back":
        batch.status = "rollback_skipped"
        batch.rolled_back_at = now
    db.commit()
    db.refresh(batch)
    return batch, changed, skipped
