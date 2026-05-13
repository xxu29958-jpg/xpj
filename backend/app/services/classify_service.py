from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import CategoryRule, Expense, RuleApplicationBatch, RuleApplicationChange
from app.services.category_service import normalize_category
from app.services.merchant_alias_service import (
    canonical_merchant_for,
    enabled_merchant_alias_map,
)
from app.services.time_service import now_utc


DEFAULT_RULES = [
    ("美团", "餐饮", 10),
    ("饿了么", "餐饮", 10),
    ("KFC", "餐饮", 20),
    ("麦当劳", "餐饮", 20),
    ("肯德基", "餐饮", 20),
    ("星巴克", "餐饮", 30),
    ("好想来", "餐饮", 20),
    ("零食", "餐饮", 30),
    ("小吃", "餐饮", 30),
    ("罗森", "餐饮", 30),
    ("便利店", "餐饮", 40),
    ("京东", "购物", 10),
    ("淘宝", "购物", 10),
    ("拼多多", "购物", 10),
    ("超市", "购物", 30),
    ("批发", "购物", 30),
    ("商超", "购物", 30),
    ("OpenAI", "AI订阅", 5),
    ("Claude", "AI订阅", 5),
    ("Gemini", "AI订阅", 5),
    ("Kimi", "AI订阅", 5),
    ("滴滴", "交通", 10),
    ("高德", "交通", 20),
    ("地铁", "交通", 20),
    ("Steam", "游戏", 10),
    ("TapTap", "游戏", 10),
    ("医院", "医疗", 10),
    ("药房", "医疗", 10),
    ("学校", "教育", 20),
    ("学费", "教育", 20),
    ("房租", "住房", 10),
    ("物业", "住房", 20),
    ("中国移动", "通讯", 10),
    ("中国联通", "通讯", 10),
    ("中国电信", "通讯", 10),
]


def seed_default_rules(db: Session, tenant_id: str) -> None:
    if db.scalar(select(CategoryRule.id).where(CategoryRule.tenant_id == tenant_id).limit(1)) is not None:
        return
    now = now_utc()
    for keyword, category, priority in DEFAULT_RULES:
        db.add(
            CategoryRule(
                tenant_id=tenant_id,
                keyword=keyword,
                category=normalize_category(category),
                enabled=True,
                priority=priority,
                created_at=now,
                updated_at=now,
            )
        )
    db.commit()


def classify_expense(db: Session, expense: Expense) -> Expense:
    alias_map = enabled_merchant_alias_map(db, tenant_id=expense.tenant_id)
    haystack = _casefold_join(
        [*_merchant_context(expense, alias_map), expense.raw_text or "", expense.note or ""]
    )
    if not haystack:
        return expense

    rules = db.scalars(
        ledger_scoped_select(CategoryRule, expense.tenant_id)
        .where(CategoryRule.enabled == True)  # noqa: E712
        .order_by(CategoryRule.priority.asc(), CategoryRule.id.asc())
    )
    for rule in rules:
        if rule.keyword.casefold() in haystack:
            expense.category = normalize_category(rule.category)
            return expense
    return expense


def list_rules(db: Session, tenant_id: str) -> list[CategoryRule]:
    return list(
        db.scalars(
            ledger_scoped_select(CategoryRule, tenant_id)
            .order_by(CategoryRule.priority.asc(), CategoryRule.id.asc())
        )
    )


def create_rule(db: Session, tenant_id: str, keyword: str, category: str, enabled: bool, priority: int) -> CategoryRule:
    keyword = keyword.strip()
    category = normalize_category(category)
    if not keyword or not category:
        raise AppError("invalid_request", status_code=422)
    now = now_utc()
    rule = CategoryRule(
        tenant_id=tenant_id,
        keyword=keyword,
        category=category,
        enabled=enabled,
        priority=priority,
        created_at=now,
        updated_at=now,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def update_rule(
    db: Session,
    rule: CategoryRule,
    *,
    keyword: str | None = None,
    category: str | None = None,
    enabled: bool | None = None,
    priority: int | None = None,
) -> CategoryRule:
    if keyword is not None:
        keyword = keyword.strip()
        if not keyword:
            raise AppError("invalid_request", status_code=422)
        rule.keyword = keyword
    if category is not None:
        category = normalize_category(category)
        if not category:
            raise AppError("invalid_request", status_code=422)
        rule.category = category
    if enabled is not None:
        rule.enabled = enabled
    if priority is not None:
        rule.priority = priority
    rule.updated_at = now_utc()
    db.commit()
    db.refresh(rule)
    return rule


def delete_rule(db: Session, rule: CategoryRule) -> None:
    db.delete(rule)
    db.commit()


# v0.4-alpha3 — Rules Engine helpers ---------------------------------

# Categories that are considered "untouched" and safe for rule auto-fill.
_AUTO_FILLABLE_CATEGORIES = {"其他", "未分类", ""}


def _casefold_join(parts: list[str]) -> str:
    return " ".join(part for part in parts if part).casefold()


def _merchant_context(expense: Expense, alias_map: dict[str, str]) -> list[str]:
    raw = expense.merchant or ""
    canonical = canonical_merchant_for(raw, alias_map=alias_map)
    if canonical and canonical != raw:
        return [raw, canonical]
    return [raw]


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
        if rule.keyword.casefold() in haystack:
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
) -> dict:
    return _preview_apply_rules_to_status(
        db,
        tenant_id=tenant_id,
        status="pending",
        limit=limit,
    )


def preview_apply_rules_to_confirmed(
    db: Session,
    *,
    tenant_id: str,
    limit: int = 20,
) -> dict:
    return _preview_apply_rules_to_status(
        db,
        tenant_id=tenant_id,
        status="confirmed",
        limit=limit,
    )


def _preview_apply_rules_to_status(
    db: Session,
    *,
    tenant_id: str,
    status: str,
    limit: int,
) -> dict:
    expenses = list(
        db.scalars(
            ledger_scoped_select(Expense, tenant_id)
            .where(Expense.status == status)
            .order_by(Expense.created_at.desc(), Expense.id.desc())
        )
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
    skipped_non_default_category = 0
    no_match_count = 0
    unchanged_count = 0
    items: list[dict] = []
    for expense in expenses:
        current_category = normalize_category(expense.category or "其他")
        if not _is_auto_fillable_category(expense.category):
            skipped_non_default_category += 1
            continue
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
    }


def apply_rules_to_pending(
    db: Session,
    *,
    tenant_id: str,
    actor_account_id: int | None = None,
    actor_device_id: int | None = None,
) -> tuple[int, int]:
    """Re-run rule classification on all pending expenses for this tenant.

    Only changes category when the current category is in
    ``_AUTO_FILLABLE_CATEGORIES`` (其他 / 未分类 / 空). Never touches confirmed
    or rejected records. Never changes the expense status — auto-confirm is
    not allowed.

    Returns ``(pending_scanned, changed_count)``.
    """
    pending = list(
        db.scalars(
            ledger_scoped_select(Expense, tenant_id)
            .where(Expense.status == "pending")
        )
    )
    rules = list(
        db.scalars(
            ledger_scoped_select(CategoryRule, tenant_id)
            .where(CategoryRule.enabled == True)  # noqa: E712
            .order_by(CategoryRule.priority.asc(), CategoryRule.id.asc())
        )
    )
    if not rules:
        return len(pending), 0

    alias_map = enabled_merchant_alias_map(db, tenant_id=tenant_id)
    changes: list[tuple[Expense, CategoryRule, str, str]] = []
    now = now_utc()
    for expense in pending:
        if not _is_auto_fillable_category(expense.category):
            continue
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
    return len(pending), len(changes)


def apply_rules_to_confirmed(
    db: Session,
    *,
    tenant_id: str,
    actor_account_id: int | None = None,
    actor_device_id: int | None = None,
) -> tuple[int, int]:
    """Apply category rules to confirmed historical rows for this tenant.

    This is intentionally separate from pending application because confirmed
    rows are historical data. It only touches confirmed expenses whose category
    is still auto-fillable (其他 / 未分类 / 空), and callers must require an
    explicit confirmation before invoking this mutating service.
    """
    confirmed = list(
        db.scalars(
            ledger_scoped_select(Expense, tenant_id)
            .where(Expense.status == "confirmed")
        )
    )
    rules = list(
        db.scalars(
            ledger_scoped_select(CategoryRule, tenant_id)
            .where(CategoryRule.enabled == True)  # noqa: E712
            .order_by(CategoryRule.priority.asc(), CategoryRule.id.asc())
        )
    )
    if not rules:
        return len(confirmed), 0

    alias_map = enabled_merchant_alias_map(db, tenant_id=tenant_id)
    changes: list[tuple[Expense, CategoryRule, str, str]] = []
    now = now_utc()
    for expense in confirmed:
        if not _is_auto_fillable_category(expense.category):
            continue
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
    return len(confirmed), len(changes)


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
