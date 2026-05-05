from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CategoryRule, Expense


DEFAULT_CATEGORIES = [
    "餐饮",
    "交通",
    "购物",
    "娱乐",
    "医疗",
    "教育",
    "住房",
    "通讯",
    "AI订阅",
    "数码",
    "游戏",
    "生活",
    "其他",
]

LEGACY_CATEGORY_ALIASES = {
    "吃饭": "餐饮",
}


def normalize_category(value: str | None) -> str:
    cleaned = (value or "其他").strip() or "其他"
    return LEGACY_CATEGORY_ALIASES.get(cleaned, cleaned)


def category_sort_key(value: str) -> tuple[int, int | str]:
    normalized = normalize_category(value)
    if normalized in DEFAULT_CATEGORIES:
        return (0, DEFAULT_CATEGORIES.index(normalized))
    return (1, normalized)


def merge_categories(values: list[str]) -> list[str]:
    categories = {normalize_category(item) for item in values if item and item.strip()}
    categories.update(DEFAULT_CATEGORIES)
    return sorted(categories, key=category_sort_key)


def normalize_existing_expense_categories(db: Session) -> None:
    changed = False
    expenses = db.scalars(select(Expense).where(Expense.category.in_(LEGACY_CATEGORY_ALIASES.keys())))
    for expense in expenses:
        normalized = normalize_category(expense.category)
        if normalized != expense.category:
            expense.category = normalized
            changed = True
    rules = db.scalars(select(CategoryRule).where(CategoryRule.category.in_(LEGACY_CATEGORY_ALIASES.keys())))
    for rule in rules:
        normalized = normalize_category(rule.category)
        if normalized != rule.category:
            rule.category = normalized
            changed = True
    if changed:
        db.commit()
