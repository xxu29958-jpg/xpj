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
    ("京东", "购物", 10),
    ("淘宝", "购物", 10),
    ("拼多多", "购物", 10),
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


def seed_default_rules(db: Session) -> None:
    if db.scalar(select(CategoryRule.id).limit(1)) is not None:
        return
    now = now_utc()
    for keyword, category, priority in DEFAULT_RULES:
        db.add(
            CategoryRule(
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
        .where(CategoryRule.enabled == True)  # noqa: E712
        .order_by(CategoryRule.priority.asc(), CategoryRule.id.asc())
    )
    for rule in rules:
        if rule.keyword.lower() in haystack:
            expense.category = normalize_category(rule.category)
            return expense
    return expense


def list_rules(db: Session) -> list[CategoryRule]:
    return list(db.scalars(select(CategoryRule).order_by(CategoryRule.priority.asc(), CategoryRule.id.asc())))


def create_rule(db: Session, keyword: str, category: str, enabled: bool, priority: int) -> CategoryRule:
    keyword = keyword.strip()
    category = normalize_category(category)
    if not keyword or not category:
        raise AppError("invalid_request", status_code=422)
    now = now_utc()
    rule = CategoryRule(
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
