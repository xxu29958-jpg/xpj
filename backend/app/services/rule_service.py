from __future__ import annotations

from datetime import datetime
from typing import Any, Final, cast

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import ObjectDeletedError

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import CategoryRule, Expense
from app.services.category_service import normalize_category
from app.services.merchant_alias_service import (
    canonical_merchant_for,
    enabled_merchant_alias_map,
)
from app.services.tag_service import parse_tags, tag_key
from app.services.time_service import ensure_utc, now_utc

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
    # v1.2 OCR single-source migration: read OCR text via the facts
    # table. ``read_ocr_text`` does the tenant-scoped lookup and
    # returns ``None`` when no fact carries text — after step 4 the
    # legacy ``expense.raw_text`` column is no longer consulted, so
    # an empty haystack means OCR never produced text for this row.
    from app.services.learning_service import read_ocr_text

    ocr_text = read_ocr_text(
        db, tenant_id=expense.tenant_id, expense=expense
    ) or ""
    haystack = _casefold_join(
        [*_merchant_context(expense, alias_map), ocr_text, expense.note or ""]
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


def find_rule_for_tenant(
    db: Session, *, tenant_id: str, rule_id: int
) -> CategoryRule | None:
    """Return a tenant-scoped ``CategoryRule`` row or ``None``.

    Used by /web rule pages where a missing rule should redirect with a
    friendly message rather than 404; the API path uses
    :func:`get_rule_for_tenant`.
    """
    return db.scalar(
        ledger_scoped_select(CategoryRule, tenant_id).where(CategoryRule.id == rule_id)
    )


def get_rule_for_tenant(db: Session, *, tenant_id: str, rule_id: int) -> CategoryRule:
    """Return a tenant-scoped ``CategoryRule`` row or raise 404.

    API-side variant: missing/cross-tenant ids must surface as
    ``rule_not_found`` so the client can react. /web pages should
    prefer :func:`find_rule_for_tenant`.
    """
    rule = find_rule_for_tenant(db, tenant_id=tenant_id, rule_id=rule_id)
    if rule is None:
        raise AppError("rule_not_found", status_code=404)
    return rule


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


def _expected_updated_at_for_db(value: datetime) -> datetime:
    """Normalize ``expected_updated_at`` for use in a ``WHERE updated_at = ?``
    predicate against ``DateTime(timezone=True)`` columns.

    SQLite stores naive ISO strings even when SQLAlchemy declares the
    column ``timezone=True``; reading back yields a naive datetime,
    and the bound parameter must match that representation. Strip
    tzinfo after normalising to UTC so the comparison is exact across
    drivers and not subject to dialect-specific aware/naive coercion.
    """
    return ensure_utc(value).replace(tzinfo=None)


def update_rule(
    db: Session,
    rule: CategoryRule,
    *,
    expected_updated_at: datetime,
    keyword: str | None = None,
    category: str | None = None,
    enabled: bool | None = None,
    priority: int | None = None,
    amount_min_cents: int | None | object = _UNSET,
    amount_max_cents: int | None | object = _UNSET,
    source_contains: str | None | object = _UNSET,
    tag_contains: str | None | object = _UNSET,
) -> CategoryRule:
    """Update a category rule with ADR-0038 atomic optimistic concurrency.

    Runs ``UPDATE category_rules SET ..., updated_at = now
    WHERE id = :id AND tenant_id = :tenant_id AND updated_at =
    :expected`` and branches on ``rowcount``. ``rowcount == 0``
    means either:

    - the row was deleted concurrently → ``rule_not_found`` 404, or
    - another writer mutated ``updated_at`` since the client's read →
      ``state_conflict`` 409.

    The DB predicate is the authoritative version check (not the
    Python-side ``rule.updated_at != expected`` comparison), so two
    sessions that both read the same ``updated_at`` and race into the
    write path cannot both win — only the first ``UPDATE WHERE`` will
    match a row.
    """
    # Snapshot identity + default-source fields up front. If a
    # concurrent session deleted this row already, the ORM instance
    # may be in the "deleted" state; surface that as 404 rather than
    # an opaque SQLAlchemy error during the UPDATE WHERE build.
    try:
        rule_id = rule.id
        rule_tenant_id = rule.tenant_id
        existing_min = rule.amount_min_cents
        existing_max = rule.amount_max_cents
    except ObjectDeletedError as exc:
        raise AppError("rule_not_found", status_code=404) from exc

    update_values: dict[str, Any] = {}
    if keyword is not None:
        cleaned = keyword.strip()
        if not cleaned:
            raise AppError("invalid_request", status_code=422)
        update_values["keyword"] = cleaned
    if category is not None:
        normalised = normalize_category(category)
        if not normalised:
            raise AppError("invalid_request", status_code=422)
        update_values["category"] = normalised
    if enabled is not None:
        update_values["enabled"] = enabled
    if priority is not None:
        update_values["priority"] = priority
    if amount_min_cents is not _UNSET or amount_max_cents is not _UNSET:
        min_value = (
            existing_min
            if amount_min_cents is _UNSET
            else cast(int | None, amount_min_cents)
        )
        max_value = (
            existing_max
            if amount_max_cents is _UNSET
            else cast(int | None, amount_max_cents)
        )
        min_value, max_value = _clean_amount_range(min_value, max_value)
        update_values["amount_min_cents"] = min_value
        update_values["amount_max_cents"] = max_value
    if source_contains is not _UNSET:
        update_values["source_contains"] = _clean_optional_text(
            cast(str | None, source_contains)
        )
    if tag_contains is not _UNSET:
        update_values["tag_contains"] = _clean_optional_text(
            cast(str | None, tag_contains)
        )
    update_values["updated_at"] = now_utc()

    expected_predicate = _expected_updated_at_for_db(expected_updated_at)
    result = db.execute(
        sa_update(CategoryRule)
        .where(CategoryRule.id == rule_id)
        .where(CategoryRule.tenant_id == rule_tenant_id)
        .where(CategoryRule.updated_at == expected_predicate)
        .values(**update_values)
    )
    if result.rowcount != 1:
        db.rollback()
        current = find_rule_for_tenant(db, tenant_id=rule_tenant_id, rule_id=rule_id)
        if current is None:
            raise AppError("rule_not_found", status_code=404)
        raise AppError("state_conflict", status_code=409)
    db.commit()
    refreshed = find_rule_for_tenant(db, tenant_id=rule_tenant_id, rule_id=rule_id)
    # rowcount == 1 means the row exists and was just updated; the
    # follow-up find cannot return None unless something else deleted
    # the row between our UPDATE and this SELECT, in which case the
    # caller should also treat it as a server-side anomaly.
    assert refreshed is not None
    return refreshed


def delete_rule(
    db: Session, rule: CategoryRule, *, expected_updated_at: datetime
) -> None:
    """Delete a category rule with ADR-0038 atomic optimistic concurrency.

    Runs ``DELETE FROM category_rules WHERE id, tenant_id, updated_at
    = expected`` and treats ``rowcount == 0`` the same way
    :func:`update_rule` does — 404 if the row vanished, 409 if it was
    mutated by a concurrent writer. The DB predicate is the
    authoritative check; the caller's ORM instance does not need to
    be fresh.
    """
    try:
        rule_id = rule.id
        rule_tenant_id = rule.tenant_id
    except ObjectDeletedError as exc:
        raise AppError("rule_not_found", status_code=404) from exc

    expected_predicate = _expected_updated_at_for_db(expected_updated_at)
    result = db.execute(
        sa_delete(CategoryRule)
        .where(CategoryRule.id == rule_id)
        .where(CategoryRule.tenant_id == rule_tenant_id)
        .where(CategoryRule.updated_at == expected_predicate)
    )
    if result.rowcount != 1:
        db.rollback()
        current = find_rule_for_tenant(db, tenant_id=rule_tenant_id, rule_id=rule_id)
        if current is None:
            raise AppError("rule_not_found", status_code=404)
        raise AppError("state_conflict", status_code=409)
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
