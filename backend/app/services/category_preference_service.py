from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import (
    Budget,
    BudgetCategory,
    CategoryPreference,
    CategoryRule,
    Expense,
    Goal,
)
from app.services.category_common import (
    DEFAULT_CATEGORIES,
    category_filter_values,
    normalize_category,
)
from app.services.optimistic_concurrency import claim_row_with_token
from app.services.soft_delete_policy import is_within_recycle_bin_window
from app.services.time_service import now_utc


@dataclass(frozen=True)
class CategoryPreferenceView:
    public_id: str
    name: str
    kind: str
    usage_count: int
    row_version: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


def clean_category_name(value: str | None) -> str:
    raw = " ".join((value or "").split())
    if not raw or len(raw) > 64:
        raise AppError("invalid_request", "分类名称不能为空。", status_code=422)
    return normalize_category(raw)


def category_preference_key(value: str | None) -> str:
    return clean_category_name(value).casefold()


def category_key_for_existing(value: str | None) -> str | None:
    raw = " ".join((value or "").split())
    if not raw:
        return None
    return normalize_category(raw).casefold()


def default_category_keys() -> set[str]:
    return {category_preference_key(item) for item in DEFAULT_CATEGORIES}


def category_preference_option_state(
    db: Session,
    *,
    tenant_id: str,
) -> tuple[list[str], set[str]]:
    rows = db.scalars(
        select(CategoryPreference)
        .where(CategoryPreference.tenant_id == tenant_id)
        .order_by(CategoryPreference.name.asc(), CategoryPreference.id.asc())
    )
    active: list[str] = []
    deleted: set[str] = set()
    for item in rows:
        if item.deleted_at is None:
            active.append(item.name)
        else:
            deleted.add(item.key)
    return active, deleted


def list_category_preferences(db: Session, *, tenant_id: str) -> list[CategoryPreferenceView]:
    usage_counts = _usage_counts_by_category_key(db, tenant_id=tenant_id)
    rows = db.scalars(
        select(CategoryPreference)
        .where(CategoryPreference.tenant_id == tenant_id)
        .where(CategoryPreference.deleted_at.is_(None))
        .order_by(CategoryPreference.name.asc(), CategoryPreference.id.asc())
    )
    return [_preference_view(item, usage_counts=usage_counts) for item in rows]


def inspect_category_preference(
    db: Session, *, tenant_id: str, public_id: str,
) -> tuple[CategoryPreferenceView, list[dict[str, str]]]:
    """Read the current option and the same blockers checked at deletion time."""
    item = _preference_by_public_id(db, tenant_id=tenant_id, public_id=public_id)
    if item is None or item.deleted_at is not None:
        raise AppError("not_found", "分类偏好不存在。", status_code=404)
    view = _preference_view(item, usage_counts=_usage_counts_by_category_key(db, tenant_id=tenant_id))
    return view, _active_category_references(db, tenant_id=tenant_id, name=item.name)


def ensure_category_preference_for_name(
    db: Session,
    *,
    tenant_id: str,
    name: str | None,
) -> CategoryPreference | None:
    """Materialize a custom category option after the user actually uses it.

    Soft-deleted rows are intentionally not auto-restored. A deleted preference
    keeps suppressing option surfaces until the explicit restore path is used.
    """
    cleaned = clean_category_name(name)
    key = category_preference_key(cleaned)
    if key in default_category_keys():
        return None
    existing = _preference_by_key(db, tenant_id=tenant_id, key=key)
    if existing is not None:
        return existing if existing.deleted_at is None else None
    now = now_utc()
    item = CategoryPreference(
        tenant_id=tenant_id,
        name=cleaned,
        key=key,
        kind="custom",
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    return item


def ensure_rule_category_available(
    db: Session,
    *,
    tenant_id: str,
    category: str,
) -> None:
    key = category_key_for_existing(category)
    if key is None:
        return
    preference = _preference_by_key(db, tenant_id=tenant_id, key=key, for_update=True)
    if preference is None or preference.deleted_at is None:
        return
    raise AppError(
        "rule_category_deleted",
        f"目标分类「{category}」已在回收站。",
        status_code=409,
        details={"category": category},
    )


def delete_category_preference(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    expected_row_version: int,
) -> CategoryPreferenceView:
    item = _preference_by_public_id(
        db,
        tenant_id=tenant_id,
        public_id=public_id,
        for_update=True,
    )
    if item is None or item.deleted_at is not None:
        raise AppError("not_found", "分类偏好不存在。", status_code=404)
    if item.kind != "custom" or item.key in default_category_keys():
        raise AppError("invalid_request", "默认分类不能删除。", status_code=422)
    _ensure_category_can_be_deleted(db, tenant_id=tenant_id, name=item.name)

    now = now_utc()
    rowcount = claim_row_with_token(
        db,
        CategoryPreference,
        pk_id=item.id,
        tenant_id=tenant_id,
        expected_row_version=expected_row_version,
        set_values={"deleted_at": now, "updated_at": now},
        extra_where=(CategoryPreference.deleted_at.is_(None),),
        synchronize_session=False,
    )
    if rowcount != 1:
        db.rollback()
        current = _preference_by_public_id(db, tenant_id=tenant_id, public_id=public_id)
        if current is None or current.deleted_at is not None:
            raise AppError("not_found", "分类偏好不存在。", status_code=404)
        raise AppError("state_conflict", status_code=409)
    db.commit()
    return _refreshed_view(db, tenant_id=tenant_id, public_id=public_id)


def restore_category_preference(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    expected_row_version: int,
) -> CategoryPreferenceView:
    item = _preference_by_public_id(db, tenant_id=tenant_id, public_id=public_id)
    if item is None or item.deleted_at is None:
        raise AppError("not_found", "分类偏好不存在。", status_code=404)
    if not is_within_recycle_bin_window(item.deleted_at):
        raise AppError("not_found", "分类偏好不存在。", status_code=404)

    now = now_utc()
    rowcount = claim_row_with_token(
        db,
        CategoryPreference,
        pk_id=item.id,
        tenant_id=tenant_id,
        expected_row_version=expected_row_version,
        set_values={"deleted_at": None, "updated_at": now},
        extra_where=(CategoryPreference.deleted_at.is_not(None),),
        synchronize_session=False,
    )
    if rowcount != 1:
        db.rollback()
        current = _preference_by_public_id(db, tenant_id=tenant_id, public_id=public_id)
        if current is None or current.deleted_at is None:
            raise AppError("not_found", "分类偏好不存在。", status_code=404)
        raise AppError("state_conflict", status_code=409)
    db.commit()
    return _refreshed_view(db, tenant_id=tenant_id, public_id=public_id)


def _refreshed_view(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
) -> CategoryPreferenceView:
    db.expire_all()
    refreshed = _preference_by_public_id(db, tenant_id=tenant_id, public_id=public_id)
    assert refreshed is not None
    return _preference_view(
        refreshed,
        usage_counts=_usage_counts_by_category_key(db, tenant_id=tenant_id),
    )


def _preference_by_public_id(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    for_update: bool = False,
) -> CategoryPreference | None:
    statement = (
        select(CategoryPreference)
        .where(CategoryPreference.tenant_id == tenant_id)
        .where(CategoryPreference.public_id == public_id)
        .limit(1)
    )
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def _preference_by_key(
    db: Session,
    *,
    tenant_id: str,
    key: str,
    for_update: bool = False,
) -> CategoryPreference | None:
    statement = (
        select(CategoryPreference)
        .where(CategoryPreference.tenant_id == tenant_id)
        .where(CategoryPreference.key == key)
        .limit(1)
    )
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def _preference_view(
    item: CategoryPreference,
    *,
    usage_counts: dict[str, int],
) -> CategoryPreferenceView:
    return CategoryPreferenceView(
        public_id=item.public_id,
        name=item.name,
        kind=item.kind,
        usage_count=int(usage_counts.get(item.key, 0)),
        row_version=item.row_version,
        created_at=item.created_at,
        updated_at=item.updated_at,
        deleted_at=item.deleted_at,
    )


def _usage_counts_by_category_key(
    db: Session,
    *,
    tenant_id: str,
) -> dict[str, int]:
    rows = db.execute(
        select(Expense.category, func.count(Expense.id))
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.category.is_not(None))
        .group_by(Expense.category)
    )
    counts: dict[str, int] = {}
    for raw_category, count in rows:
        key = category_key_for_existing(raw_category)
        if key is None:
            continue
        counts[key] = counts.get(key, 0) + int(count or 0)
    return counts


def _ensure_category_can_be_deleted(
    db: Session,
    *,
    tenant_id: str,
    name: str,
) -> None:
    references = _active_category_references(db, tenant_id=tenant_id, name=name)
    if references:
        raise AppError(
            "state_conflict",
            "这个分类仍被规则、预算或目标使用，请先处理相关配置。",
            status_code=409,
            details={"category_references": references},
        )


def _active_category_references(
    db: Session,
    *,
    tenant_id: str,
    name: str,
) -> list[dict[str, str]]:
    values = category_filter_values(name)
    rules = db.scalars(
        select(CategoryRule)
        .where(CategoryRule.tenant_id == tenant_id)
        .where(CategoryRule.deleted_at.is_(None))
        .where(CategoryRule.enabled.is_(True))
        .where(CategoryRule.category.in_(values))
        .order_by(CategoryRule.id.asc())
    )
    references = [
        {"kind": "rule", "id": str(rule.id), "label": f"规则「{rule.keyword}」"}
        for rule in rules
    ]
    category_budget_months = set(
        db.scalars(
            select(BudgetCategory.month)
            .join(
                Budget,
                (Budget.tenant_id == BudgetCategory.tenant_id)
                & (Budget.month == BudgetCategory.month),
            )
            .where(BudgetCategory.tenant_id == tenant_id)
            .where(BudgetCategory.category.in_(values))
            .where(Budget.archived_at.is_(None))
        )
    )
    key = category_preference_key(name)
    budgets = db.scalars(
        select(Budget)
        .where(Budget.tenant_id == tenant_id)
        .where(Budget.archived_at.is_(None))
        .order_by(Budget.month.asc())
    )
    references.extend(
        {"kind": "budget", "id": budget.month, "label": f"预算「{budget.month}」"}
        for budget in budgets
        if budget.month in category_budget_months
        or key in _parse_budget_excluded_category_keys(budget.excluded_categories)
    )
    goals = db.scalars(
        select(Goal)
        .where(Goal.tenant_id == tenant_id)
        .where(Goal.status == "active")
        .where(Goal.goal_type == "spending_limit")
        .where(Goal.category.in_(values))
        .order_by(Goal.id.asc())
    )
    references.extend(
        {"kind": "goal", "id": goal.public_id, "label": f"目标「{goal.name}」"}
        for goal in goals
    )
    return references


def _parse_budget_excluded_category_keys(value: str | None) -> set[str]:
    if not value:
        return set()
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return set()
    if not isinstance(parsed, list):
        return set()
    return {
        key
        for item in parsed
        if isinstance(item, str) and (key := category_key_for_existing(item))
    }
