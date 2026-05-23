"""Pure category-name helpers shared between category_service and
spending_contract_service.

Extracted to break the category_service ↔ spending_contract_service
cycle: spending_contract_service.confirmed_query lazy-imported
``category_filter_values`` from category_service, while
category_service.list_category_summary top-level-imported
``month_bounds_utc`` / ``stat_time_expr`` from spending_contract_service.
With both pulling the pure name helpers from this third module, the
cycle goes away.

This module is pure (no DB, no Session) — the surrounding category
write paths (``normalize_existing_expense_categories`` etc.) stay in
category_service.
"""

from __future__ import annotations

__all__ = [
    "DEFAULT_CATEGORIES",
    "LEGACY_CATEGORY_ALIASES",
    "category_filter_values",
    "normalize_category",
]

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


def category_filter_values(category: str | None) -> set[str]:
    normalized = normalize_category(category)
    values = {normalized}
    values.update(
        legacy
        for legacy, canonical in LEGACY_CATEGORY_ALIASES.items()
        if canonical == normalized
    )
    return values
