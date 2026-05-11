from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import CategoryRule, Expense
from app.services.category_service import normalize_category
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
    haystack = " ".join(
        part for part in [expense.merchant or "", expense.raw_text or "", expense.note or ""] if part
    ).lower()
    if not haystack:
        return expense

    rules = db.scalars(
        select(CategoryRule)
        .where(CategoryRule.tenant_id == expense.tenant_id)
        .where(CategoryRule.enabled == True)  # noqa: E712
        .order_by(CategoryRule.priority.asc(), CategoryRule.id.asc())
    )
    for rule in rules:
        if rule.keyword.lower() in haystack:
            expense.category = normalize_category(rule.category)
            return expense
    return expense


def list_rules(db: Session, tenant_id: str) -> list[CategoryRule]:
    return list(
        db.scalars(
            select(CategoryRule)
            .where(CategoryRule.tenant_id == tenant_id)
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


def _haystack_for(expense: Expense, match_field: str) -> str:
    field = (match_field or "merchant").strip().lower()
    if field == "merchant":
        return (expense.merchant or "").lower()
    if field in {"raw_text", "raw"}:
        return (expense.raw_text or "").lower()
    # "any" or unrecognized → match against merchant + raw_text + note
    return " ".join(
        part
        for part in [
            expense.merchant or "",
            expense.raw_text or "",
            expense.note or "",
        ]
        if part
    ).lower()


def _is_auto_fillable_category(value: str | None) -> bool:
    return normalize_category(value or "") in _AUTO_FILLABLE_CATEGORIES


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
    needle = keyword_clean.lower()
    field_label = {"merchant": "商家", "raw_text": "原文", "any": "原文/备注/商家"}.get(
        (match_field or "merchant").strip().lower(), "商家"
    )
    suggested = normalize_category(target_category) if target_category else None

    pending = db.scalars(
        select(Expense)
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.status == "pending")
        .order_by(Expense.created_at.desc(), Expense.id.desc())
    )
    matched: list[dict] = []
    matched_count = 0
    capped = max(1, min(int(limit or 10), 50))
    for expense in pending:
        if needle not in _haystack_for(expense, match_field):
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


def apply_rules_to_pending(db: Session, *, tenant_id: str) -> tuple[int, int]:
    """Re-run rule classification on all pending expenses for this tenant.

    Only changes category when the current category is in
    ``_AUTO_FILLABLE_CATEGORIES`` (其他 / 未分类 / 空). Never touches confirmed
    or rejected records. Never changes the expense status — auto-confirm is
    not allowed.

    Returns ``(pending_scanned, changed_count)``.
    """
    pending = list(
        db.scalars(
            select(Expense)
            .where(Expense.tenant_id == tenant_id)
            .where(Expense.status == "pending")
        )
    )
    rules = list(
        db.scalars(
            select(CategoryRule)
            .where(CategoryRule.tenant_id == tenant_id)
            .where(CategoryRule.enabled == True)  # noqa: E712
            .order_by(CategoryRule.priority.asc(), CategoryRule.id.asc())
        )
    )
    if not rules:
        return len(pending), 0

    changed = 0
    now = now_utc()
    for expense in pending:
        if not _is_auto_fillable_category(expense.category):
            continue
        haystack = " ".join(
            part
            for part in [
                expense.merchant or "",
                expense.raw_text or "",
                expense.note or "",
            ]
            if part
        ).lower()
        if not haystack:
            continue
        for rule in rules:
            if rule.keyword.lower() in haystack:
                new_category = normalize_category(rule.category)
                if new_category and new_category != expense.category:
                    expense.category = new_category
                    expense.updated_at = now
                    changed += 1
                break
    if changed:
        db.commit()
    return len(pending), changed
