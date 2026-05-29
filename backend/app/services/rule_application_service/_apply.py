"""Apply rule classifications + write audit batch + change records."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.ledger_scope import ledger_scoped_select
from app.models import CategoryRule, RuleApplicationBatch, RuleApplicationChange
from app.services.category_service import normalize_category
from app.services.merchant_alias_service import enabled_merchant_alias_map
from app.services.rule_application_service._common import (
    _matching_rule_category,
    _ocr_text_by_expense_id,
    _rule_application_candidates,
    _try_apply_rule_category,
)
from app.services.time_service import now_utc


def apply_rules_to_pending(
    db: Session,
    *,
    tenant_id: str,
    actor_account_id: int | None = None,
    actor_device_id: int | None = None,
    max_scan: int | None = None,
) -> tuple[int, int, bool]:
    """Re-run rule classification on all pending expenses for this tenant.

    Only changes category when the current category is in
    ``_AUTO_FILLABLE_CATEGORIES`` (其他 / 未分类 / 空). Never touches confirmed
    or rejected records. Never changes the expense status — auto-confirm is
    not allowed.

    Returns ``(pending_scanned, changed_count, scan_limit_reached)``.
    """
    return _apply_rules_to_status(
        db,
        tenant_id=tenant_id,
        status="pending",
        audit_status="applied",
        actor_account_id=actor_account_id,
        actor_device_id=actor_device_id,
        max_scan=max_scan,
    )


def apply_rules_to_confirmed(
    db: Session,
    *,
    tenant_id: str,
    actor_account_id: int | None = None,
    actor_device_id: int | None = None,
    max_scan: int | None = None,
) -> tuple[int, int, bool]:
    """Apply category rules to confirmed historical rows for this tenant.

    This is intentionally separate from pending application because confirmed
    rows are historical data. It only touches confirmed expenses whose category
    is still auto-fillable (其他 / 未分类 / 空), and callers must require an
    explicit confirmation before invoking this mutating service.
    """
    return _apply_rules_to_status(
        db,
        tenant_id=tenant_id,
        status="confirmed",
        audit_status="applied_confirmed",
        actor_account_id=actor_account_id,
        actor_device_id=actor_device_id,
        max_scan=max_scan,
    )


def _apply_rules_to_status(
    db: Session,
    *,
    tenant_id: str,
    status: str,
    audit_status: str,
    actor_account_id: int | None,
    actor_device_id: int | None,
    max_scan: int | None,
) -> tuple[int, int, bool]:
    expenses, scan_limit_reached = _rule_application_candidates(
        db,
        tenant_id=tenant_id,
        status=status,
        max_scan=max_scan,
    )
    rules = list(
        db.scalars(
            ledger_scoped_select(CategoryRule, tenant_id)
            .where(CategoryRule.enabled == True)  # noqa: E712
            .where(CategoryRule.deleted_at.is_(None))
            .order_by(CategoryRule.priority.asc(), CategoryRule.id.asc())
        )
    )
    if not rules:
        return len(expenses), 0, scan_limit_reached

    alias_map = enabled_merchant_alias_map(db, tenant_id=tenant_id)
    ocr_text_by_id = _ocr_text_by_expense_id(
        db, tenant_id=tenant_id, expenses=expenses
    )
    changes: list[tuple[int, int, str, str, str]] = []
    now = now_utc()
    for expense in expenses:
        match = _matching_rule_category(
            expense,
            rules,
            alias_map,
            ocr_text=ocr_text_by_id.get(int(expense.id), ""),
        )
        if match is None:
            continue
        rule, new_category = match
        before_category = normalize_category(expense.category)
        if new_category == before_category:
            continue
        applied = _try_apply_rule_category(
            db,
            tenant_id=tenant_id,
            status=status,
            expense=expense,
            rule=rule,
            before_category=before_category,
            after_category=new_category,
            now=now,
        )
        if applied is not None:
            changes.append(applied)
    if changes:
        batch = RuleApplicationBatch(
            tenant_id=tenant_id,
            status=audit_status,
            pending_scanned=len(expenses),
            changed_count=len(changes),
            actor_account_id=actor_account_id,
            actor_device_id=actor_device_id,
            created_at=now,
        )
        db.add(batch)
        db.flush()
        for expense_id, rule_id, matched_keyword, before_category, after_category in changes:
            db.add(
                RuleApplicationChange(
                    tenant_id=tenant_id,
                    batch_id=batch.id,
                    expense_id=expense_id,
                    rule_id=rule_id,
                    matched_keyword=matched_keyword,
                    before_category=before_category,
                    after_category=after_category,
                    status="applied",
                    created_at=now,
                )
            )
        db.commit()
    return len(expenses), len(changes), scan_limit_reached
