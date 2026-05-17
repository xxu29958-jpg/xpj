from __future__ import annotations

import hashlib
import json

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_filter, ledger_scoped_select
from app.models import CategoryRule, Expense, RuleApplicationBatch, RuleApplicationChange
from app.services.category_service import normalize_category
from app.services.merchant_alias_service import enabled_merchant_alias_map
from app.services.rule_service import (
    _casefold_join,
    _merchant_context,
    _rule_conditions_match,
)
from app.services.time_service import now_utc


# Categories that are considered "untouched" and safe for rule auto-fill.
_AUTO_FILLABLE_CATEGORIES = {"其他", "未分类", ""}
DEFAULT_RULE_APPLICATION_SCAN_LIMIT = 500


def _clamp_rule_application_scan_limit(value: int | None) -> int:
    return max(1, min(int(value or DEFAULT_RULE_APPLICATION_SCAN_LIMIT), 1000))


def _auto_fillable_category_filter():
    return or_(Expense.category.is_(None), Expense.category.in_(_AUTO_FILLABLE_CATEGORIES))


def _rule_application_candidates(
    db: Session,
    *,
    tenant_id: str,
    status: str,
    max_scan: int | None = None,
) -> tuple[list[Expense], bool]:
    capped = _clamp_rule_application_scan_limit(max_scan)
    rows = list(
        db.scalars(
            ledger_scoped_select(Expense, tenant_id)
            .where(Expense.status == status)
            .where(_auto_fillable_category_filter())
            .order_by(Expense.created_at.desc(), Expense.id.desc())
            .limit(capped + 1)
        )
    )
    return rows[:capped], len(rows) > capped


def _non_auto_fillable_category_count(db: Session, *, tenant_id: str, status: str) -> int:
    count = db.scalar(
        select(func.count())
        .select_from(Expense)
        .where(ledger_filter(Expense, tenant_id))
        .where(Expense.status == status)
        .where(~_auto_fillable_category_filter())
    )
    return int(count or 0)


def _iso_or_none(value: object) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value)


def _rule_application_preview_token(
    *,
    status: str,
    max_scan: int | None,
    expenses: list[Expense],
    rules: list[CategoryRule],
    alias_map: dict[str, str],
) -> str:
    payload = {
        "version": 1,
        "status": status,
        "scan_limit": _clamp_rule_application_scan_limit(max_scan),
        "aliases": sorted(alias_map.items()),
        "expenses": [
            {
                "id": expense.id,
                "category": normalize_category(expense.category or ""),
                "amount_cents": expense.amount_cents,
                "merchant": expense.merchant or "",
                "raw_text": expense.raw_text or "",
                "note": expense.note or "",
                "source": expense.source or "",
                "tags": expense.tags or "",
                "updated_at": _iso_or_none(expense.updated_at),
            }
            for expense in expenses
        ],
        "rules": [
            {
                "id": rule.id,
                "keyword": rule.keyword,
                "category": normalize_category(rule.category),
                "priority": rule.priority,
                "amount_min_cents": rule.amount_min_cents,
                "amount_max_cents": rule.amount_max_cents,
                "source_contains": rule.source_contains,
                "tag_contains": rule.tag_contains,
                "updated_at": _iso_or_none(rule.updated_at),
            }
            for rule in rules
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _haystack_for(expense: Expense, match_field: str, alias_map: dict[str, str]) -> str:
    field = (match_field or "merchant").strip().lower()
    if field == "merchant":
        return _casefold_join(_merchant_context(expense, alias_map))
    if field in {"raw_text", "raw"}:
        return (expense.raw_text or "").casefold()
    # "any" or unrecognized → match against merchant + raw_text + note
    return _casefold_join(
        [*_merchant_context(expense, alias_map), expense.raw_text or "", expense.note or ""]
    )


def _is_auto_fillable_category(value: str | None) -> bool:
    return normalize_category(value or "") in _AUTO_FILLABLE_CATEGORIES


def _matching_rule_category(
    expense: Expense,
    rules: list[CategoryRule],
    alias_map: dict[str, str],
) -> tuple[CategoryRule, str] | None:
    haystack = _haystack_for(expense, "any", alias_map)
    if not haystack:
        return None
    for rule in rules:
        if rule.keyword.casefold() in haystack and _rule_conditions_match(expense, rule):
            category = normalize_category(rule.category)
            if category:
                return rule, category
            return None
    return None


def preview_rule_for_pending(
    db: Session,
    *,
    tenant_id: str,
    keyword: str,
    target_category: str | None,
    match_field: str = "merchant",
    limit: int = 10,
) -> tuple[int, list[dict]]:
    """Return (matched_count, items) for keyword match over pending expenses.

    Pure preview — does **not** mutate database. Only scans pending records.
    """
    keyword_clean = (keyword or "").strip()
    if not keyword_clean:
        raise AppError("invalid_request", status_code=422)
    needle = keyword_clean.casefold()
    field_label = {"merchant": "商家", "raw_text": "原文", "any": "原文/备注/商家"}.get(
        (match_field or "merchant").strip().lower(), "商家"
    )
    suggested = normalize_category(target_category) if target_category else None

    pending = db.scalars(
        ledger_scoped_select(Expense, tenant_id)
        .where(Expense.status == "pending")
        .order_by(Expense.created_at.desc(), Expense.id.desc())
    )
    alias_map = enabled_merchant_alias_map(db, tenant_id=tenant_id)
    matched: list[dict] = []
    matched_count = 0
    capped = max(1, min(int(limit or 10), 50))
    for expense in pending:
        if needle not in _haystack_for(expense, match_field, alias_map):
            continue
        matched_count += 1
        if len(matched) >= capped:
            continue
        matched.append(
            {
                "id": expense.id,
                "merchant": expense.merchant,
                "amount_cents": expense.amount_cents,
                "current_category": normalize_category(expense.category or "其他"),
                "suggested_category": suggested,
                "reason": f"{field_label}包含 {keyword_clean}",
            }
        )
    return matched_count, matched


def preview_apply_rules_to_pending(
    db: Session,
    *,
    tenant_id: str,
    limit: int = 20,
    max_scan: int | None = None,
) -> dict:
    return _preview_apply_rules_to_status(
        db,
        tenant_id=tenant_id,
        status="pending",
        limit=limit,
        max_scan=max_scan,
    )


def preview_apply_rules_to_confirmed(
    db: Session,
    *,
    tenant_id: str,
    limit: int = 20,
    max_scan: int | None = None,
) -> dict:
    return _preview_apply_rules_to_status(
        db,
        tenant_id=tenant_id,
        status="confirmed",
        limit=limit,
        max_scan=max_scan,
    )


def _preview_apply_rules_to_status(
    db: Session,
    *,
    tenant_id: str,
    status: str,
    limit: int,
    max_scan: int | None,
) -> dict:
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
            .order_by(CategoryRule.priority.asc(), CategoryRule.id.asc())
        )
    )
    alias_map = enabled_merchant_alias_map(db, tenant_id=tenant_id)
    capped = max(1, min(int(limit or 20), 50))

    changed_count = 0
    skipped_non_default_category = _non_auto_fillable_category_count(
        db,
        tenant_id=tenant_id,
        status=status,
    )
    no_match_count = 0
    unchanged_count = 0
    items: list[dict] = []
    for expense in expenses:
        current_category = normalize_category(expense.category or "其他")
        match = _matching_rule_category(expense, rules, alias_map)
        if match is None:
            no_match_count += 1
            continue
        rule, suggested_category = match
        if suggested_category == current_category:
            unchanged_count += 1
            continue
        changed_count += 1
        if len(items) >= capped:
            continue
        items.append(
            {
                "id": expense.id,
                "merchant": expense.merchant,
                "current_category": current_category,
                "suggested_category": suggested_category,
                "rule_keyword": rule.keyword,
                "reason": f"规则[{rule.keyword}] 将分类改为 {suggested_category}",
            }
        )

    return {
        "scanned": len(expenses),
        "pending_scanned": len(expenses),
        "confirmed_scanned": len(expenses),
        "changed_count": changed_count,
        "items": items,
        "skipped_non_default_category": skipped_non_default_category,
        "no_match_count": no_match_count,
        "unchanged_count": unchanged_count,
        "conflict_count": 0,
        "scan_limit_reached": scan_limit_reached,
        "scan_limit": _clamp_rule_application_scan_limit(max_scan),
        "preview_token": _rule_application_preview_token(
            status=status,
            max_scan=max_scan,
            expenses=expenses,
            rules=rules,
            alias_map=alias_map,
        ),
    }


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
    pending, scan_limit_reached = _rule_application_candidates(
        db,
        tenant_id=tenant_id,
        status="pending",
        max_scan=max_scan,
    )
    rules = list(
        db.scalars(
            ledger_scoped_select(CategoryRule, tenant_id)
            .where(CategoryRule.enabled == True)  # noqa: E712
            .order_by(CategoryRule.priority.asc(), CategoryRule.id.asc())
        )
    )
    if not rules:
        return len(pending), 0, scan_limit_reached

    alias_map = enabled_merchant_alias_map(db, tenant_id=tenant_id)
    changes: list[tuple[Expense, CategoryRule, str, str]] = []
    now = now_utc()
    for expense in pending:
        match = _matching_rule_category(expense, rules, alias_map)
        if match is None:
            continue
        rule, new_category = match
        before_category = normalize_category(expense.category)
        if new_category != before_category:
            expense.category = new_category
            expense.updated_at = now
            changes.append((expense, rule, before_category, new_category))
    if changes:
        batch = RuleApplicationBatch(
            tenant_id=tenant_id,
            status="applied",
            pending_scanned=len(pending),
            changed_count=len(changes),
            actor_account_id=actor_account_id,
            actor_device_id=actor_device_id,
            created_at=now,
        )
        db.add(batch)
        db.flush()
        for expense, rule, before_category, after_category in changes:
            db.add(
                RuleApplicationChange(
                    tenant_id=tenant_id,
                    batch_id=batch.id,
                    expense_id=expense.id,
                    rule_id=rule.id,
                    matched_keyword=rule.keyword,
                    before_category=before_category,
                    after_category=after_category,
                    status="applied",
                    created_at=now,
                )
            )
        db.commit()
    return len(pending), len(changes), scan_limit_reached


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
    confirmed, scan_limit_reached = _rule_application_candidates(
        db,
        tenant_id=tenant_id,
        status="confirmed",
        max_scan=max_scan,
    )
    rules = list(
        db.scalars(
            ledger_scoped_select(CategoryRule, tenant_id)
            .where(CategoryRule.enabled == True)  # noqa: E712
            .order_by(CategoryRule.priority.asc(), CategoryRule.id.asc())
        )
    )
    if not rules:
        return len(confirmed), 0, scan_limit_reached

    alias_map = enabled_merchant_alias_map(db, tenant_id=tenant_id)
    changes: list[tuple[Expense, CategoryRule, str, str]] = []
    now = now_utc()
    for expense in confirmed:
        match = _matching_rule_category(expense, rules, alias_map)
        if match is None:
            continue
        rule, new_category = match
        before_category = normalize_category(expense.category)
        if new_category != before_category:
            expense.category = new_category
            expense.updated_at = now
            changes.append((expense, rule, before_category, new_category))
    if changes:
        batch = RuleApplicationBatch(
            tenant_id=tenant_id,
            status="applied_confirmed",
            pending_scanned=len(confirmed),
            changed_count=len(changes),
            actor_account_id=actor_account_id,
            actor_device_id=actor_device_id,
            created_at=now,
        )
        db.add(batch)
        db.flush()
        for expense, rule, before_category, after_category in changes:
            db.add(
                RuleApplicationChange(
                    tenant_id=tenant_id,
                    batch_id=batch.id,
                    expense_id=expense.id,
                    rule_id=rule.id,
                    matched_keyword=rule.keyword,
                    before_category=before_category,
                    after_category=after_category,
                    status="applied",
                    created_at=now,
                )
            )
        db.commit()
    return len(confirmed), len(changes), scan_limit_reached


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
        if expense is None or normalize_category(expense.category) != change.after_category:
            change.status = "skipped"
            change.rolled_back_at = now
            skipped += 1
            continue
        expense.category = change.before_category
        expense.updated_at = now
        change.status = "rolled_back"
        change.rolled_back_at = now
        changed += 1

    if batch.status != "rolled_back":
        batch.status = "rolled_back"
        batch.rolled_back_at = now
    db.commit()
    db.refresh(batch)
    return batch, changed, skipped
