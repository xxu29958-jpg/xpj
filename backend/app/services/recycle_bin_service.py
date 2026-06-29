"""Current-ledger recycle-bin aggregation (ADR-0051 web/Android slice).

The owner-console implementation stays loopback and multi-ledger. This module is
the app-token/web-session counterpart: it only sees the caller's current ledger,
uses the explicit recycle-bin retention window for soft-deleted rows, and
delegates restore operations to the resource services that already own OCC and
audit behaviour.
"""

from __future__ import annotations

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
    Goal,
    MerchantAlias,
    MonthlyIncomePlan,
    RecurringItem,
    Tag,
    TagMutationUndoGroup,
)
from app.services.budget_service import list_archived_budgets, restore_monthly_budget
from app.services.category_preference_service import restore_category_preference
from app.services.classify_service import undo_delete_rule
from app.services.goal_service import restore_goal
from app.services.income_plan_service import restore_income_plan
from app.services.merchant_alias_service import undo_delete_merchant_alias
from app.services.recurring_service import restore_recurring_item
from app.services.soft_delete_policy import (
    is_within_recycle_bin_window,
    recycle_bin_retention_label,
)
from app.services.tag_undo_service import undo_tag_mutation


@dataclass(frozen=True)
class RecycleBinItem:
    kind: str
    kind_label: str
    resource_id: str
    title: str
    detail: str
    removed_at: datetime | None
    retention_label: str
    expected_row_version: int | None


@dataclass(frozen=True)
class RecycleBinListing:
    items: list[RecycleBinItem]
    short_window_count: int


def list_recycle_bin_items(db: Session, *, tenant_id: str) -> RecycleBinListing:
    rows: list[RecycleBinItem] = []
    rows.extend(_archived_budget_rows(db, tenant_id))
    rows.extend(_soft_deleted_category_preference_rows(db, tenant_id))
    rows.extend(_archived_income_rows(db, tenant_id))
    rows.extend(_archived_recurring_rows(db, tenant_id))
    rows.extend(_archived_goal_rows(db, tenant_id))
    rows.extend(_soft_deleted_rule_rows(db, tenant_id))
    rows.extend(_soft_deleted_alias_rows(db, tenant_id))
    rows.extend(_tag_undo_rows(db, tenant_id))
    rows.sort(key=_sort_key, reverse=True)
    return RecycleBinListing(
        items=rows,
        short_window_count=sum(1 for row in rows if row.retention_label != "长期保留"),
    )


def restore_recycle_bin_item(
    db: Session,
    *,
    tenant_id: str,
    kind: str,
    resource_id: str,
    expected_row_version: int | None,
    actor_account_id: int | None,
) -> str:
    clean_kind = (kind or "").strip()
    clean_resource_id = (resource_id or "").strip()
    if not clean_kind or not clean_resource_id:
        raise AppError("invalid_request", "恢复参数不完整。", status_code=422)

    if clean_kind == "income_plan":
        return _restore_income_plan_item(
            db, tenant_id, clean_resource_id, expected_row_version
        )
    if clean_kind == "monthly_budget":
        restore_monthly_budget(
            db,
            tenant_id=tenant_id,
            month=clean_resource_id,
            expected_row_version=_require_token(expected_row_version),
        )
        return "月度预算已恢复。"
    if clean_kind == "category_preference":
        return _restore_category_preference_item(
            db, tenant_id, clean_resource_id, expected_row_version
        )
    if clean_kind == "recurring_item":
        restore_recurring_item(
            db,
            tenant_id=tenant_id,
            public_id=clean_resource_id,
            expected_row_version=_require_token(expected_row_version),
        )
        return "固定支出已恢复。"
    if clean_kind == "goal":
        restore_goal(
            db,
            tenant_id=tenant_id,
            public_id=clean_resource_id,
            expected_row_version=_require_token(expected_row_version),
        )
        return "目标已恢复。"
    if clean_kind == "category_rule":
        undo_delete_rule(
            db,
            tenant_id=tenant_id,
            rule_id=_parse_rule_id(clean_resource_id),
            actor_account_id=actor_account_id,
            use_recycle_bin_window=True,
        )
        return "分类规则已恢复。"
    if clean_kind == "merchant_alias":
        undo_delete_merchant_alias(
            db,
            tenant_id=tenant_id,
            public_id=clean_resource_id,
            actor_account_id=actor_account_id,
            use_recycle_bin_window=True,
        )
        return "商家别名已恢复。"
    if clean_kind == "tag_mutation":
        result = undo_tag_mutation(
            db,
            tenant_id=tenant_id,
            mutation_public_id=clean_resource_id,
            expected_row_version=_require_token(expected_row_version),
            actor_account_id=actor_account_id,
            use_recycle_bin_window=True,
        )
        if result.skipped:
            return f"标签已恢复；恢复 {result.applied} 笔，跳过 {result.skipped} 笔已变更账单。"
        return f"标签已恢复；恢复 {result.applied} 笔账单。"
    raise AppError("invalid_request", "不支持的回收站项目。", status_code=422)


def _require_token(value: int | None) -> int:
    if value is None:
        raise AppError("invalid_request", "页面已过期，请刷新后重试。", status_code=422)
    return int(value)


def _restore_income_plan_item(
    db: Session,
    tenant_id: str,
    public_id: str,
    expected_row_version: int | None,
) -> str:
    restore_income_plan(
        db,
        tenant_id=tenant_id,
        public_id=public_id,
        expected_row_version=_require_token(expected_row_version),
    )
    return "收入记录已恢复。"


def _restore_category_preference_item(
    db: Session,
    tenant_id: str,
    public_id: str,
    expected_row_version: int | None,
) -> str:
    restore_category_preference(
        db,
        tenant_id=tenant_id,
        public_id=public_id,
        expected_row_version=_require_token(expected_row_version),
    )
    return "分类已恢复。"


def _parse_rule_id(value: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise AppError("invalid_request", "恢复参数不完整。", status_code=422) from exc


def _sort_key(row: RecycleBinItem) -> datetime:
    return row.removed_at or datetime.min


def _archived_income_rows(db: Session, tenant_id: str) -> list[RecycleBinItem]:
    rows = db.scalars(
        select(MonthlyIncomePlan)
        .where(MonthlyIncomePlan.tenant_id == tenant_id)
        .where(MonthlyIncomePlan.status == "archived")
        .order_by(MonthlyIncomePlan.archived_at.desc(), MonthlyIncomePlan.id.desc())
    )
    return [
        RecycleBinItem(
            kind="income_plan",
            kind_label="收入",
            resource_id=item.public_id,
            title=item.label,
            detail=_income_detail(item),
            removed_at=item.archived_at,
            retention_label="长期保留",
            expected_row_version=item.row_version,
        )
        for item in rows
    ]


def _archived_budget_rows(db: Session, tenant_id: str) -> list[RecycleBinItem]:
    return [
        RecycleBinItem(
            kind="monthly_budget",
            kind_label="预算",
            resource_id=item.month,
            title=f"{item.month} 月度预算",
            detail=_budget_detail(db, item),
            removed_at=item.archived_at,
            retention_label="长期保留",
            expected_row_version=item.row_version,
        )
        for item in list_archived_budgets(db, tenant_id=tenant_id)
    ]


def _soft_deleted_category_preference_rows(
    db: Session, tenant_id: str
) -> list[RecycleBinItem]:
    rows = [
        item
        for item in db.scalars(
            select(CategoryPreference)
            .where(CategoryPreference.tenant_id == tenant_id)
            .where(CategoryPreference.deleted_at.is_not(None))
            .order_by(CategoryPreference.deleted_at.desc(), CategoryPreference.id.desc())
        )
        if is_within_recycle_bin_window(item.deleted_at)
    ]
    return [
        RecycleBinItem(
            kind="category_preference",
            kind_label="分类",
            resource_id=item.public_id,
            title=item.name,
            detail="自定义分类选项",
            removed_at=item.deleted_at,
            retention_label=recycle_bin_retention_label(),
            expected_row_version=item.row_version,
        )
        for item in rows
    ]


def _archived_recurring_rows(db: Session, tenant_id: str) -> list[RecycleBinItem]:
    rows = db.scalars(
        select(RecurringItem)
        .where(RecurringItem.tenant_id == tenant_id)
        .where(RecurringItem.status == "archived")
        .order_by(RecurringItem.archived_at.desc(), RecurringItem.id.desc())
    )
    return [
        RecycleBinItem(
            kind="recurring_item",
            kind_label="固定支出",
            resource_id=item.public_id,
            title=item.merchant_name,
            detail=f"每月 {_money(item.baseline_amount_cents)} · 已出现 {item.occurrence_count} 次",
            removed_at=item.archived_at,
            retention_label="长期保留",
            expected_row_version=item.row_version,
        )
        for item in rows
    ]


def _archived_goal_rows(db: Session, tenant_id: str) -> list[RecycleBinItem]:
    rows = db.scalars(
        select(Goal)
        .where(Goal.tenant_id == tenant_id)
        .where(Goal.status == "archived")
        .order_by(Goal.archived_at.desc(), Goal.id.desc())
    )
    return [
        RecycleBinItem(
            kind="goal",
            kind_label="目标",
            resource_id=item.public_id,
            title=item.name,
            detail=_goal_detail(item),
            removed_at=item.archived_at,
            retention_label="长期保留",
            expected_row_version=item.row_version,
        )
        for item in rows
    ]


def _soft_deleted_rule_rows(db: Session, tenant_id: str) -> list[RecycleBinItem]:
    rows = [
        item
        for item in db.scalars(
            select(CategoryRule)
            .where(CategoryRule.tenant_id == tenant_id)
            .where(CategoryRule.deleted_at.is_not(None))
            .order_by(CategoryRule.deleted_at.desc(), CategoryRule.id.desc())
        )
        if is_within_recycle_bin_window(item.deleted_at)
    ]
    return [
        RecycleBinItem(
            kind="category_rule",
            kind_label="分类规则",
            resource_id=str(item.id),
            title=item.keyword,
            detail=f"匹配后分类为 {item.category}",
            removed_at=item.deleted_at,
            retention_label=recycle_bin_retention_label(),
            expected_row_version=None,
        )
        for item in rows
    ]


def _soft_deleted_alias_rows(db: Session, tenant_id: str) -> list[RecycleBinItem]:
    rows = [
        item
        for item in db.scalars(
            select(MerchantAlias)
            .where(MerchantAlias.tenant_id == tenant_id)
            .where(MerchantAlias.deleted_at.is_not(None))
            .order_by(MerchantAlias.deleted_at.desc(), MerchantAlias.id.desc())
        )
        if is_within_recycle_bin_window(item.deleted_at)
    ]
    return [
        RecycleBinItem(
            kind="merchant_alias",
            kind_label="商家别名",
            resource_id=item.public_id,
            title=item.alias,
            detail=f"恢复为 {item.canonical_merchant} 的别名",
            removed_at=item.deleted_at,
            retention_label=recycle_bin_retention_label(),
            expected_row_version=None,
        )
        for item in rows
    ]


def _tag_undo_rows(db: Session, tenant_id: str) -> list[RecycleBinItem]:
    rows: list[RecycleBinItem] = []
    query_rows = db.execute(
        select(TagMutationUndoGroup, Tag)
        .join(
            Tag,
            (Tag.tenant_id == TagMutationUndoGroup.tenant_id)
            & (Tag.public_id == TagMutationUndoGroup.source_tag_public_id),
        )
        .where(TagMutationUndoGroup.tenant_id == tenant_id)
        .where(TagMutationUndoGroup.consumed_at.is_(None))
        .where(Tag.deleted_at.is_not(None))
        .order_by(TagMutationUndoGroup.created_at.desc(), TagMutationUndoGroup.id.desc())
    ).all()
    for group, tag in query_rows:
        if not is_within_recycle_bin_window(group.created_at):
            continue
        detail = "删除标签"
        if group.op == "merge" and group.target_tag_name:
            detail = f"从「{group.target_tag_name}」里拆回"
        rows.append(
            RecycleBinItem(
                kind="tag_mutation",
                kind_label="标签",
                resource_id=group.mutation_public_id,
                title=group.source_tag_name,
                detail=detail,
                removed_at=group.created_at,
                retention_label=recycle_bin_retention_label(),
                expected_row_version=tag.row_version,
            )
        )
    return rows


def _income_detail(item: MonthlyIncomePlan) -> str:
    frequency = "每月固定" if item.frequency == "monthly" else f"{item.income_month} 到账"
    return f"{frequency} · {_money(item.amount_cents)} · {item.pay_day} 号"


def _goal_detail(item: Goal) -> str:
    if item.goal_type == "debt_repayment":
        return "还债目标"
    scope = item.category or "总支出"
    return f"{item.month} · {scope} · 目标 {_money(item.target_amount_cents or 0)}"


def _budget_detail(db: Session, item: Budget) -> str:
    category_count = db.scalar(
        select(func.count(BudgetCategory.id))
        .where(BudgetCategory.tenant_id == item.tenant_id)
        .where(BudgetCategory.month == item.month)
    )
    return (
        f"总预算 {_money(item.total_amount_cents)} · "
        f"分类预算 {int(category_count or 0)} 项"
    )


def _money(amount_cents: int) -> str:
    return f"¥{int(amount_cents or 0) / 100:.2f}"


__all__ = [
    "RecycleBinItem",
    "RecycleBinListing",
    "list_recycle_bin_items",
    "restore_recycle_bin_item",
]
