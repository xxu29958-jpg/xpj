from __future__ import annotations

from typing import Final, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import CategoryRule, Expense
from app.services.category_service import normalize_category
from app.services.merchant_alias_service import (
    canonical_merchant_for,
    enabled_merchant_alias_map,
)
from app.services.tag_service import parse_tags, tag_key
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

_UNSET: Final = object()


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
        if rule.keyword.casefold() in haystack and _rule_conditions_match(expense, rule):
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


def create_rule(
    db: Session,
    tenant_id: str,
    keyword: str,
    category: str,
    enabled: bool,
    priority: int,
    amount_min_cents: int | None = None,
    amount_max_cents: int | None = None,
    source_contains: str | None = None,
    tag_contains: str | None = None,
) -> CategoryRule:
    keyword = keyword.strip()
    category = normalize_category(category)
    source_contains = _clean_optional_text(source_contains)
    tag_contains = _clean_optional_text(tag_contains)
    amount_min_cents, amount_max_cents = _clean_amount_range(amount_min_cents, amount_max_cents)
    if not keyword or not category:
        raise AppError("invalid_request", status_code=422)
    now = now_utc()
    rule = CategoryRule(
        tenant_id=tenant_id,
        keyword=keyword,
        category=category,
        enabled=enabled,
        priority=priority,
        amount_min_cents=amount_min_cents,
        amount_max_cents=amount_max_cents,
        source_contains=source_contains,
        tag_contains=tag_contains,
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
    amount_min_cents: int | None | object = _UNSET,
    amount_max_cents: int | None | object = _UNSET,
    source_contains: str | None | object = _UNSET,
    tag_contains: str | None | object = _UNSET,
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
    if amount_min_cents is not _UNSET or amount_max_cents is not _UNSET:
        min_value = (
            rule.amount_min_cents
            if amount_min_cents is _UNSET
            else cast(int | None, amount_min_cents)
        )
        max_value = (
            rule.amount_max_cents
            if amount_max_cents is _UNSET
            else cast(int | None, amount_max_cents)
        )
        rule.amount_min_cents, rule.amount_max_cents = _clean_amount_range(min_value, max_value)
    if source_contains is not _UNSET:
        rule.source_contains = _clean_optional_text(cast(str | None, source_contains))
    if tag_contains is not _UNSET:
        rule.tag_contains = _clean_optional_text(cast(str | None, tag_contains))
    rule.updated_at = now_utc()
    db.commit()
    db.refresh(rule)
    return rule


def delete_rule(db: Session, rule: CategoryRule) -> None:
    db.delete(rule)
    db.commit()


# Shared matching helpers used by rule_service and rule_application_service.


def _casefold_join(parts: list[str]) -> str:
    return " ".join(part for part in parts if part).casefold()


def _merchant_context(expense: Expense, alias_map: dict[str, str]) -> list[str]:
    raw = expense.merchant or ""
    canonical = canonical_merchant_for(raw, alias_map=alias_map)
    if canonical and canonical != raw:
        return [raw, canonical]
    return [raw]


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _clean_amount_range(
    amount_min_cents: int | None,
    amount_max_cents: int | None,
) -> tuple[int | None, int | None]:
    if amount_min_cents is not None and amount_min_cents < 0:
        raise AppError("invalid_request", "金额下限不能为负数。", status_code=422)
    if amount_max_cents is not None and amount_max_cents < 0:
        raise AppError("invalid_request", "金额上限不能为负数。", status_code=422)
    if (
        amount_min_cents is not None
        and amount_max_cents is not None
        and amount_min_cents > amount_max_cents
    ):
        raise AppError("invalid_request", "金额下限不能大于上限。", status_code=422)
    return amount_min_cents, amount_max_cents


def _rule_conditions_match(expense: Expense, rule: CategoryRule) -> bool:
    amount = expense.amount_cents
    if rule.amount_min_cents is not None and (amount is None or amount < rule.amount_min_cents):
        return False
    if rule.amount_max_cents is not None and (amount is None or amount > rule.amount_max_cents):
        return False
    if rule.source_contains and rule.source_contains.casefold() not in (expense.source or "").casefold():
        return False
    if rule.tag_contains:
        wanted = tag_key(rule.tag_contains)
        if wanted not in {tag_key(tag) for tag in parse_tags(expense.tags)}:
            return False
    return True
