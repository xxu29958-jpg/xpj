from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import CategoryRule, Expense
from app.money_contract import projection_sum_to_int
from app.schemas import ExpenseUpdateRequest
from app.services.category_common import (
    DEFAULT_CATEGORIES,
    LEGACY_CATEGORY_ALIASES,
    category_filter_values,
    normalize_category,
)
from app.services.category_preference_service import (
    category_key_for_existing,
    category_preference_option_state,
    default_category_keys,
)
from app.services.currency_binding_service import authorize_currency_metadata_write
from app.services.data_quality_service import is_uncategorized_expense_category
from app.services.expense_revision_service import (
    prepare_correction_revision,
    record_prepared_correction_revision,
)
from app.services.optimistic_concurrency import bump_row_version
from app.services.spending_contract_service import confirmed_stream_query

# Re-exports — existing callers do
# ``from app.services.category_service import normalize_category`` etc.
# Keep that surface stable.
__all_category_helpers = (
    DEFAULT_CATEGORIES,
    LEGACY_CATEGORY_ALIASES,
    category_filter_values,
    normalize_category,
)


def category_sort_key(value: str) -> tuple[int, int | str]:
    normalized = normalize_category(value)
    if normalized in DEFAULT_CATEGORIES:
        return (0, DEFAULT_CATEGORIES.index(normalized))
    return (1, normalized)


def merge_categories(
    values: list[str],
    *,
    suppressed_keys: set[str] | None = None,
) -> list[str]:
    suppressed = suppressed_keys or set()
    defaults = default_category_keys()
    categories = {
        normalize_category(item)
        for item in values
        if item
        and item.strip()
        and ((key := category_key_for_existing(item)) is not None and (key not in suppressed or key in defaults))
    }
    categories.update(DEFAULT_CATEGORIES)
    return sorted(categories, key=category_sort_key)


def list_ledger_category_options(db: Session, *, tenant_id: str) -> list[str]:
    """Categories to offer as a ``<datalist>`` autocomplete on the edit page:
    the ledger's own already-used categories unioned with ``DEFAULT_CATEGORIES``,
    legacy aliases normalised, defaults first then the rest alphabetically.

    Pure suggestion surface — the category field stays free text (AI/OCR only
    fills blanks, ENGINEERING_RULES §8). The datalist just curbs spelling drift
    (餐饮 vs 餐厅) at the input.
    """
    used = list(
        db.scalars(
            select(Expense.category)
            .where(Expense.tenant_id == tenant_id)
            .where(Expense.category.is_not(None))
            .distinct()
        )
    )
    active_names, deleted_keys = category_preference_option_state(db, tenant_id=tenant_id)
    return merge_categories(
        [str(value) for value in used] + active_names,
        suppressed_keys=deleted_keys,
    )


def normalize_existing_expense_categories(db: Session, tenant_id: str) -> None:
    changed = False
    expenses = list(
        db.scalars(
            select(Expense)
            .where(Expense.tenant_id == tenant_id)
            .where(Expense.category.in_(LEGACY_CATEGORY_ALIASES.keys()))
        )
    )
    rules = list(
        db.scalars(
            select(CategoryRule)
            .where(CategoryRule.tenant_id == tenant_id)
            .where(CategoryRule.deleted_at.is_(None))
            .where(CategoryRule.category.in_(LEGACY_CATEGORY_ALIASES.keys()))
        )
    )
    if not expenses and not rules:
        return
    rules_are_non_financial = all(rule.amount_min_cents is None and rule.amount_max_cents is None for rule in rules)
    authorize_currency_metadata_write(
        db,
        allow_empty_category_rule=not expenses and rules_are_non_financial,
    )
    for expense in expenses:
        normalized = normalize_category(expense.category)
        if normalized != expense.category:
            prepared = prepare_correction_revision(db, expense)
            expense.category = normalized
            if prepared is not None:
                bump_row_version(expense)
                expense.fact_revision = Expense.fact_revision + 1
                db.flush()
                db.refresh(expense)
                record_prepared_correction_revision(
                    db,
                    expense,
                    prepared,
                    reason="系统统一历史分类名称",
                    actor_account_id=None,
                    actor_device_id=None,
                )
            changed = True
    for rule in rules:
        normalized = normalize_category(rule.category)
        if normalized != rule.category:
            rule.category = normalized
            changed = True
    if changed:
        db.commit()


# ── /web/categories dashboard (v0.4-alpha3 slice 2 / M3 / T12-T13) ─────────


def _is_cleanup_pending_category(value: str | None) -> bool:
    """Triage-backlog caliber for the cleanup workflow: the shared
    uncategorized tokens (blank / 未分类 / 未分類 / none / null,
    case-insensitive, ported in data_quality_service) PLUS 「其他」.

    The two legs have different intents, deliberately: data-quality's
    missing_category treats 其他 as a valid user category (it doesn't defeat
    stats slicing), while this workflow exists to triage the upload backlog —
    and uploads default to 其他 (expense_service/_create), so the
    not-yet-triaged rows live there. Keeping 其他 is codified by main's own
    tests (test_web_categories_counts_pending_uncategorized /
    test_web_uncategorized_lists_only_uncategorized)."""
    return (value or "").strip() == "其他" or is_uncategorized_expense_category(value)


@dataclass
class CategorySummary:
    category: str
    confirmed_count: int
    pending_count: int
    confirmed_amount_cents: int
    is_uncategorized: bool


@dataclass
class CategoryDashboard:
    month: str
    summaries: list[CategorySummary] = field(default_factory=list)
    rule_count: int = 0
    uncategorized_pending: int = 0


def _display_category(key: str) -> str:
    return key or "未分类"


def _is_uncategorized_category(key: str) -> bool:
    return _is_cleanup_pending_category(key)


def _pending_counts_by_category(db: Session, *, tenant_id: str) -> dict[str, int]:
    pending_rows = db.execute(
        select(Expense.category, func.count(Expense.id))
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.status == "pending")
        .group_by(Expense.category)
    ).all()
    pending_by_category: dict[str, int] = {}
    for category, count in pending_rows:
        key = normalize_category(category)
        pending_by_category[key] = pending_by_category.get(key, 0) + int(count)
    return pending_by_category


def _confirmed_summaries_by_category(
    db: Session,
    *,
    tenant_id: str,
    month: str,
    timezone_name: str | None,
    pending_by_category: dict[str, int],
) -> dict[str, CategorySummary]:
    stream = confirmed_stream_query(
        tenant_id=tenant_id,
        month=month,
        timezone_name=timezone_name,
        amount_required=True,
    )
    confirmed_rows = db.execute(
        select(
            stream.c.category,
            func.count(stream.c.entry_id),
            func.coalesce(func.sum(stream.c.stream_amount_cents), 0),
        )
        .select_from(stream)
        .group_by(stream.c.category)
    ).all()

    aggregated: dict[str, CategorySummary] = {}
    for category, count, amount in confirmed_rows:
        key = normalize_category(category)
        confirmed_count = int(count)
        confirmed_amount = projection_sum_to_int(
            amount,
            label="category.confirmed_amount",
            empty_is_zero=True,
        )
        existing = aggregated.get(key)
        if existing is None:
            aggregated[key] = CategorySummary(
                category=_display_category(key),
                confirmed_count=confirmed_count,
                pending_count=int(pending_by_category.get(key, 0)),
                confirmed_amount_cents=confirmed_amount,
                is_uncategorized=_is_uncategorized_category(key),
            )
            continue
        aggregated[key] = CategorySummary(
            category=existing.category,
            confirmed_count=existing.confirmed_count + confirmed_count,
            pending_count=existing.pending_count,
            confirmed_amount_cents=projection_sum_to_int(
                existing.confirmed_amount_cents + confirmed_amount,
                label="category.normalized_confirmed_amount",
            ),
            is_uncategorized=existing.is_uncategorized,
        )
    return aggregated


def _add_pending_only_summaries(aggregated: dict[str, CategorySummary], pending_by_category: dict[str, int]) -> None:
    for key, count in pending_by_category.items():
        if key in aggregated:
            continue
        aggregated[key] = CategorySummary(
            category=_display_category(key),
            confirmed_count=0,
            pending_count=int(count),
            confirmed_amount_cents=0,
            is_uncategorized=_is_uncategorized_category(key),
        )


def _sort_category_summaries(
    aggregated: dict[str, CategorySummary],
) -> list[CategorySummary]:
    return sorted(
        aggregated.values(),
        key=lambda s: (s.is_uncategorized, -s.confirmed_amount_cents, s.category),
    )


def _category_rule_count(db: Session, *, tenant_id: str) -> int:
    return int(
        db.scalar(
            select(func.count(CategoryRule.id))
            .where(CategoryRule.tenant_id == tenant_id)
            .where(CategoryRule.deleted_at.is_(None))
        )
        or 0
    )


def list_category_summary(
    db: Session, *, tenant_id: str, month: str, timezone_name: str | None = None
) -> CategoryDashboard:
    """Return per-category counts/amounts for the dashboard.

    Confirmed amounts/counts use the shared financial-event projection: roots
    use their local expense/confirmation date, offsets their accounting date.
    Pending counts are global per category so the user can see lingering
    uncategorized rows regardless of month.
    """
    pending_by_category = _pending_counts_by_category(db, tenant_id=tenant_id)
    aggregated = _confirmed_summaries_by_category(
        db,
        tenant_id=tenant_id,
        month=month,
        timezone_name=timezone_name,
        pending_by_category=pending_by_category,
    )
    _add_pending_only_summaries(aggregated, pending_by_category)
    summaries = _sort_category_summaries(aggregated)
    uncategorized_pending = sum(s.pending_count for s in summaries if s.is_uncategorized)
    return CategoryDashboard(
        month=month,
        summaries=summaries,
        rule_count=_category_rule_count(db, tenant_id=tenant_id),
        uncategorized_pending=uncategorized_pending,
    )


def list_uncategorized_pending(db: Session, *, tenant_id: str) -> list[Expense]:
    """Return pending rows in the triage backlog (see
    ``_is_cleanup_pending_category``): blank / 其他 / 未分类 / 未分類 /
    none / null, case-insensitive."""
    categories = (
        db.execute(
            select(Expense.category).where(Expense.tenant_id == tenant_id).where(Expense.status == "pending").distinct()
        )
        .scalars()
        .all()
    )
    matching = [category for category in categories if _is_cleanup_pending_category(category)]
    if not matching:
        return []
    rows = (
        db.execute(
            select(Expense)
            .where(Expense.tenant_id == tenant_id)
            .where(Expense.status == "pending")
            .where(Expense.category.in_(matching))
            .order_by(Expense.created_at.desc())
            .limit(200)
        )
        .scalars()
        .all()
    )
    return list(rows)


def bulk_set_category(db: Session, *, tenant_id: str, expense_ids: list[int], category: str) -> int:
    """Set ``category`` on the given pending rows. Returns the changed count.

    Skips any id not visible to ``tenant_id`` or not in ``pending`` status,
    instead of raising — the bulk action is best-effort and the page will
    re-render the remaining rows after the redirect.
    """
    if not expense_ids:
        return 0
    authorize_currency_metadata_write(db)
    cleaned_category = (category or "").strip()
    if not cleaned_category:
        raise AppError("invalid_request", "请选择一个分类。", status_code=400)
    if not expense_ids:
        return 0
    from app.services.expense_service import update_expense  # lazy import: expense_service imports from this module

    rows = (
        db.execute(
            select(Expense)
            .where(Expense.tenant_id == tenant_id)
            .where(Expense.id.in_(expense_ids))
            .where(Expense.status == "pending")
        )
        .scalars()
        .all()
    )
    changed = 0
    # ADR-0038 PR-2a / ADR-0041: 服务端 bulk 操作刚读到 row.row_version，可以直接
    # 当作 expected_row_version 喂给 update_expense（保留 PATCH 路径的原子
    # UPDATE WHERE row_version 语义，但不要求外部调用方携带 token）。
    for row in rows:
        payload = ExpenseUpdateRequest(
            category=cleaned_category,
            expected_row_version=row.row_version,
        )
        update_expense(db, row.id, tenant_id, payload)
        changed += 1
    return changed
