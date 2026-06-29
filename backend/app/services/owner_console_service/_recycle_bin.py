"""Unified recycle-bin view-models for Owner Console.

Archived rows stay visible until restored. Soft-deleted rows use ADR-0051's
explicit recycle-bin retention window, while the original undo endpoints keep
their short 5-minute banner window. This module aggregates those
resource-specific lifecycles into one owner-only surface.
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
    Ledger,
    LedgerMember,
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
from app.services.owner_console_service._common import _amount_yuan, get_owner_account_id
from app.services.owner_console_service._ledger_console import (
    do_unarchive_ledger,
    list_archived_console_ledgers,
    list_manageable_console_ledgers,
)
from app.services.recurring_service import restore_recurring_item
from app.services.soft_delete_policy import (
    is_within_recycle_bin_window,
    recycle_bin_retention_label,
)
from app.services.tag_undo_service import undo_tag_mutation


@dataclass(frozen=True)
class RecycleBinItemVM:
    kind: str
    kind_label: str
    ledger_id: str
    ledger_name: str
    resource_id: str
    title: str
    detail: str
    removed_at: datetime | str | None
    retention_label: str
    expected_row_version: int | None


@dataclass(frozen=True)
class RecycleBinVM:
    rows: list[RecycleBinItemVM]
    ledger_count: int
    short_window_count: int


def get_recycle_bin_vm(db: Session) -> RecycleBinVM:
    ledger_names = _active_ledger_names(db)
    rows: list[RecycleBinItemVM] = []
    rows.extend(_archived_ledger_rows(db))
    if ledger_names:
        rows.extend(_archived_budget_rows(db, ledger_names))
        rows.extend(_soft_deleted_category_rows(db, ledger_names))
        rows.extend(_archived_income_rows(db, ledger_names))
        rows.extend(_archived_recurring_rows(db, ledger_names))
        rows.extend(_archived_goal_rows(db, ledger_names))
        rows.extend(_soft_deleted_rule_rows(db, ledger_names))
        rows.extend(_soft_deleted_alias_rows(db, ledger_names))
        rows.extend(_tag_undo_rows(db, ledger_names))
    rows.sort(key=_sort_key, reverse=True)
    return RecycleBinVM(
        rows=rows,
        ledger_count=len(ledger_names),
        short_window_count=sum(1 for row in rows if row.retention_label != "长期保留"),
    )


def restore_recycle_bin_item(
    db: Session,
    *,
    kind: str,
    ledger_id: str,
    resource_id: str,
    expected_row_version: int | None,
) -> str:
    owner_id = get_owner_account_id(db)
    if owner_id is None:
        raise AppError("invalid_request", "服务未初始化。", status_code=409)

    clean_kind = (kind or "").strip()
    clean_ledger_id = (ledger_id or "").strip()
    clean_resource_id = (resource_id or "").strip()
    if not clean_kind or not clean_resource_id:
        raise AppError("invalid_request", "恢复参数不完整。", status_code=422)

    if clean_kind == "ledger":
        do_unarchive_ledger(db, ledger_id=clean_resource_id)
        return "账本已恢复。"

    _require_active_owner_ledger(db, clean_ledger_id)
    if clean_kind == "income_plan":
        restore_income_plan(
            db,
            tenant_id=clean_ledger_id,
            public_id=clean_resource_id,
            expected_row_version=_require_token(expected_row_version),
        )
        return "收入记录已恢复。"
    if clean_kind == "monthly_budget":
        restore_monthly_budget(
            db,
            tenant_id=clean_ledger_id,
            month=clean_resource_id,
            expected_row_version=_require_token(expected_row_version),
        )
        return "月度预算已恢复。"
    if clean_kind == "category_preference":
        restore_category_preference(
            db, tenant_id=clean_ledger_id, public_id=clean_resource_id,
            expected_row_version=_require_token(expected_row_version),
        )
        return "分类已恢复。"
    if clean_kind == "recurring_item":
        restore_recurring_item(
            db,
            tenant_id=clean_ledger_id,
            public_id=clean_resource_id,
            expected_row_version=_require_token(expected_row_version),
        )
        return "固定支出已恢复。"
    if clean_kind == "goal":
        restore_goal(
            db,
            tenant_id=clean_ledger_id,
            public_id=clean_resource_id,
            expected_row_version=_require_token(expected_row_version),
        )
        return "目标已恢复。"
    if clean_kind == "category_rule":
        undo_delete_rule(
            db,
            tenant_id=clean_ledger_id,
            rule_id=int(clean_resource_id),
            actor_account_id=owner_id,
            use_recycle_bin_window=True,
        )
        return "分类规则已恢复。"
    if clean_kind == "merchant_alias":
        undo_delete_merchant_alias(
            db,
            tenant_id=clean_ledger_id,
            public_id=clean_resource_id,
            actor_account_id=owner_id,
            use_recycle_bin_window=True,
        )
        return "商家别名已恢复。"
    if clean_kind == "tag_mutation":
        result = undo_tag_mutation(
            db,
            tenant_id=clean_ledger_id,
            mutation_public_id=clean_resource_id,
            expected_row_version=_require_token(expected_row_version),
            actor_account_id=owner_id,
            use_recycle_bin_window=True,
        )
        if result.skipped:
            return f"标签已恢复；恢复 {result.applied} 笔，跳过 {result.skipped} 笔已变更账单。"
        return f"标签已恢复；恢复 {result.applied} 笔账单。"
    raise AppError("invalid_request", "不支持的回收站项目。", status_code=422)


def _active_ledger_names(db: Session) -> dict[str, str]:
    return {row.ledger_id: row.name for row in list_manageable_console_ledgers(db)}


def _require_active_owner_ledger(db: Session, ledger_id: str) -> None:
    if ledger_id not in _active_ledger_names(db):
        raise AppError("ledger_forbidden", "账本不可用或不属于当前 owner。", status_code=403)


def _require_token(value: int | None) -> int:
    if value is None:
        raise AppError("invalid_request", "页面已过期，请刷新后重试。", status_code=422)
    return int(value)


def _sort_key(row: RecycleBinItemVM) -> datetime:
    value = row.removed_at
    if isinstance(value, datetime):
        return value
    return datetime.min


def _archived_ledger_rows(db: Session) -> list[RecycleBinItemVM]:
    archived_at_by_ledger = _archived_ledger_times(db)
    return [
        RecycleBinItemVM(
            kind="ledger",
            kind_label="账本",
            ledger_id=row.ledger_id,
            ledger_name=row.name,
            resource_id=row.ledger_id,
            title=row.name,
            detail=f"待确认 {row.pending_count} 条 · 已确认 {row.confirmed_count} 条",
            removed_at=archived_at_by_ledger.get(row.ledger_id),
            retention_label="长期保留",
            expected_row_version=None,
        )
        for row in list_archived_console_ledgers(db)
    ]


def _archived_ledger_times(db: Session) -> dict[str, datetime | None]:
    owner_id = get_owner_account_id(db)
    if owner_id is None:
        return {}
    rows = db.execute(
        select(Ledger.ledger_id, Ledger.archived_at)
        .join(LedgerMember, LedgerMember.ledger_id == Ledger.ledger_id)
        .where(LedgerMember.account_id == owner_id)
        .where(LedgerMember.role == "owner")
        .where(LedgerMember.disabled_at.is_(None))
        .where(Ledger.archived_at.is_not(None))
    ).all()
    return dict(rows)


def _archived_income_rows(
    db: Session, ledger_names: dict[str, str]
) -> list[RecycleBinItemVM]:
    rows = db.scalars(
        select(MonthlyIncomePlan)
        .where(MonthlyIncomePlan.tenant_id.in_(list(ledger_names)))
        .where(MonthlyIncomePlan.status == "archived")
        .order_by(MonthlyIncomePlan.archived_at.desc(), MonthlyIncomePlan.id.desc())
    )
    return [
        RecycleBinItemVM(
            kind="income_plan",
            kind_label="收入",
            ledger_id=item.tenant_id,
            ledger_name=ledger_names[item.tenant_id],
            resource_id=item.public_id,
            title=item.label,
            detail=_income_detail(item),
            removed_at=item.archived_at,
            retention_label="长期保留",
            expected_row_version=item.row_version,
        )
        for item in rows
    ]


def _archived_budget_rows(
    db: Session, ledger_names: dict[str, str]
) -> list[RecycleBinItemVM]:
    rows: list[RecycleBinItemVM] = []
    for ledger_id, ledger_name in ledger_names.items():
        for item in list_archived_budgets(db, tenant_id=ledger_id):
            rows.append(
                RecycleBinItemVM(
                    kind="monthly_budget",
                    kind_label="预算",
                    ledger_id=item.tenant_id,
                    ledger_name=ledger_name,
                    resource_id=item.month,
                    title=f"{item.month} 月度预算",
                    detail=_budget_detail(db, item),
                    removed_at=item.archived_at,
                    retention_label="长期保留",
                    expected_row_version=item.row_version,
                )
            )
    return rows


def _soft_deleted_category_rows(db: Session, ledger_names: dict[str, str]) -> list[RecycleBinItemVM]:
    items = db.scalars(
        select(CategoryPreference)
        .where(CategoryPreference.tenant_id.in_(list(ledger_names)))
        .where(CategoryPreference.deleted_at.is_not(None))
        .order_by(CategoryPreference.deleted_at.desc(), CategoryPreference.id.desc())
    )
    return [
        RecycleBinItemVM(
            kind="category_preference", kind_label="分类",
            ledger_id=item.tenant_id, ledger_name=ledger_names[item.tenant_id],
            resource_id=item.public_id,
            title=item.name,
            detail="自定义分类选项", removed_at=item.deleted_at,
            retention_label=recycle_bin_retention_label(),
            expected_row_version=item.row_version,
        )
        for item in items
        if is_within_recycle_bin_window(item.deleted_at)
    ]


def _archived_recurring_rows(
    db: Session, ledger_names: dict[str, str]
) -> list[RecycleBinItemVM]:
    rows = db.scalars(
        select(RecurringItem)
        .where(RecurringItem.tenant_id.in_(list(ledger_names)))
        .where(RecurringItem.status == "archived")
        .order_by(RecurringItem.archived_at.desc(), RecurringItem.id.desc())
    )
    return [
        RecycleBinItemVM(
            kind="recurring_item",
            kind_label="固定支出",
            ledger_id=item.tenant_id,
            ledger_name=ledger_names[item.tenant_id],
            resource_id=item.public_id,
            title=item.merchant_name,
            detail=f"每月 {_money(item.baseline_amount_cents)} · 已出现 {item.occurrence_count} 次",
            removed_at=item.archived_at,
            retention_label="长期保留",
            expected_row_version=item.row_version,
        )
        for item in rows
    ]


def _archived_goal_rows(
    db: Session, ledger_names: dict[str, str]
) -> list[RecycleBinItemVM]:
    rows = db.scalars(
        select(Goal)
        .where(Goal.tenant_id.in_(list(ledger_names)))
        .where(Goal.status == "archived")
        .order_by(Goal.archived_at.desc(), Goal.id.desc())
    )
    return [
        RecycleBinItemVM(
            kind="goal",
            kind_label="目标",
            ledger_id=item.tenant_id,
            ledger_name=ledger_names[item.tenant_id],
            resource_id=item.public_id,
            title=item.name,
            detail=_goal_detail(item),
            removed_at=item.archived_at,
            retention_label="长期保留",
            expected_row_version=item.row_version,
        )
        for item in rows
    ]


def _soft_deleted_rule_rows(
    db: Session, ledger_names: dict[str, str]
) -> list[RecycleBinItemVM]:
    rows = [
        item
        for item in db.scalars(
            select(CategoryRule)
            .where(CategoryRule.tenant_id.in_(list(ledger_names)))
            .where(CategoryRule.deleted_at.is_not(None))
            .order_by(CategoryRule.deleted_at.desc(), CategoryRule.id.desc())
        )
        if is_within_recycle_bin_window(item.deleted_at)
    ]
    return [
        RecycleBinItemVM(
            kind="category_rule",
            kind_label="分类规则",
            ledger_id=item.tenant_id,
            ledger_name=ledger_names[item.tenant_id],
            resource_id=str(item.id),
            title=item.keyword,
            detail=f"匹配后分类为 {item.category}",
            removed_at=item.deleted_at,
            retention_label=recycle_bin_retention_label(),
            expected_row_version=None,
        )
        for item in rows
    ]


def _soft_deleted_alias_rows(
    db: Session, ledger_names: dict[str, str]
) -> list[RecycleBinItemVM]:
    rows = [
        item
        for item in db.scalars(
            select(MerchantAlias)
            .where(MerchantAlias.tenant_id.in_(list(ledger_names)))
            .where(MerchantAlias.deleted_at.is_not(None))
            .order_by(MerchantAlias.deleted_at.desc(), MerchantAlias.id.desc())
        )
        if is_within_recycle_bin_window(item.deleted_at)
    ]
    return [
        RecycleBinItemVM(
            kind="merchant_alias",
            kind_label="商家别名",
            ledger_id=item.tenant_id,
            ledger_name=ledger_names[item.tenant_id],
            resource_id=item.public_id,
            title=item.alias,
            detail=f"恢复为 {item.canonical_merchant} 的别名",
            removed_at=item.deleted_at,
            retention_label=recycle_bin_retention_label(),
            expected_row_version=None,
        )
        for item in rows
    ]


def _tag_undo_rows(
    db: Session, ledger_names: dict[str, str]
) -> list[RecycleBinItemVM]:
    rows = []
    query_rows = db.execute(
        select(TagMutationUndoGroup, Tag)
        .join(
            Tag,
            (Tag.tenant_id == TagMutationUndoGroup.tenant_id)
            & (Tag.public_id == TagMutationUndoGroup.source_tag_public_id),
        )
        .where(TagMutationUndoGroup.tenant_id.in_(list(ledger_names)))
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
            RecycleBinItemVM(
                kind="tag_mutation",
                kind_label="标签",
                ledger_id=group.tenant_id,
                ledger_name=ledger_names[group.tenant_id],
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
    return "¥" + _amount_yuan(int(amount_cents or 0))


__all__ = [
    "RecycleBinItemVM",
    "RecycleBinVM",
    "get_recycle_bin_vm",
    "restore_recycle_bin_item",
]
