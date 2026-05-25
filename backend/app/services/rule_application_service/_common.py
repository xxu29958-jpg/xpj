"""Shared helpers for preview / apply / history of rule application."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.ledger_scope import ledger_filter, ledger_scoped_select
from app.models import CategoryRule, Expense, OcrFact, RuleApplicationChange
from app.services.category_service import normalize_category
from app.services.ocr_service import ocr_draft_fields_after_clearing
from app.services.rule_service import (
    _casefold_join,
    _merchant_context,
    _rule_conditions_match,
)

# Categories that are considered "untouched" and safe for rule auto-fill.
_AUTO_FILLABLE_CATEGORIES = {"其他", "未分类", ""}
DEFAULT_RULE_APPLICATION_SCAN_LIMIT = 500


def _clamp_rule_application_scan_limit(value: int | None) -> int:
    return max(1, min(int(value or DEFAULT_RULE_APPLICATION_SCAN_LIMIT), 1000))


def _auto_fillable_category_filter():
    return or_(Expense.category.is_(None), Expense.category.in_(_AUTO_FILLABLE_CATEGORIES))


def _rule_application_candidates(
    db: Session,
    *,
    tenant_id: str,
    status: str,
    max_scan: int | None = None,
) -> tuple[list[Expense], bool]:
    capped = _clamp_rule_application_scan_limit(max_scan)
    rows = list(
        db.scalars(
            ledger_scoped_select(Expense, tenant_id)
            .where(Expense.status == status)
            .where(_auto_fillable_category_filter())
            .order_by(Expense.created_at.desc(), Expense.id.desc())
            .limit(capped + 1)
        )
    )
    return rows[:capped], len(rows) > capped


def _non_auto_fillable_category_count(db: Session, *, tenant_id: str, status: str) -> int:
    count = db.scalar(
        select(func.count())
        .select_from(Expense)
        .where(ledger_filter(Expense, tenant_id))
        .where(Expense.status == status)
        .where(~_auto_fillable_category_filter())
    )
    return int(count or 0)


def _iso_or_none(value: object) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value)


def _ocr_text_by_expense_id(
    db: Session,
    *,
    tenant_id: str,
    expenses: list[Expense],
) -> dict[int, str]:
    """Bulk variant of read_ocr_text for rule preview/apply scans.

    Mirrors the single-expense ``read_ocr_text`` contract: the latest
    fact's ``raw_text`` is the only source. After v1.2 step 4 the
    legacy ``expense.raw_text`` column is **not** consulted, so an
    expense with no fact (or whose latest fact carries empty
    ``raw_text``) maps to ``""``. Step 3's backfill guarantees this
    matches what the single-expense path returns for the same row.
    """

    result: dict[int, str] = {}
    expense_ids: list[int] = []
    for expense in expenses:
        expense_id = expense.id
        if expense_id is None:
            continue
        expense_id = int(expense_id)
        result[expense_id] = ""
        if expense.tenant_id != tenant_id:
            continue
        expense_ids.append(expense_id)

    if not expense_ids:
        return result

    rows = db.execute(
        select(OcrFact.expense_id, OcrFact.raw_text)
        .where(OcrFact.tenant_id == tenant_id)
        .where(OcrFact.expense_id.in_(expense_ids))
        .order_by(
            OcrFact.expense_id.asc(),
            OcrFact.extracted_at.desc(),
            OcrFact.id.desc(),
        )
    )
    seen: set[int] = set()
    for expense_id, raw_text in rows:
        expense_id = int(expense_id)
        if expense_id in seen:
            continue
        seen.add(expense_id)
        if raw_text:
            result[expense_id] = raw_text
    return result


def _rule_application_preview_token(
    *,
    status: str,
    max_scan: int | None,
    expenses: list[Expense],
    rules: list[CategoryRule],
    alias_map: dict[str, str],
    ocr_text_by_id: dict[int, str],
) -> str:
    payload = {
        "version": 1,
        "status": status,
        "scan_limit": _clamp_rule_application_scan_limit(max_scan),
        "aliases": sorted(alias_map.items()),
        "expenses": [
            {
                "id": expense.id,
                "category": normalize_category(expense.category or ""),
                "amount_cents": expense.amount_cents,
                "merchant": expense.merchant or "",
                "raw_text": ocr_text_by_id.get(expense.id, ""),
                "note": expense.note or "",
                "source": expense.source or "",
                "tags": expense.tags or "",
                "updated_at": _iso_or_none(expense.updated_at),
            }
            for expense in expenses
        ],
        "rules": [
            {
                "id": rule.id,
                "keyword": rule.keyword,
                "category": normalize_category(rule.category),
                "priority": rule.priority,
                "amount_min_cents": rule.amount_min_cents,
                "amount_max_cents": rule.amount_max_cents,
                "source_contains": rule.source_contains,
                "tag_contains": rule.tag_contains,
                "updated_at": _iso_or_none(rule.updated_at),
            }
            for rule in rules
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _haystack_for(
    expense: Expense,
    match_field: str,
    alias_map: dict[str, str],
    *,
    ocr_text: str = "",
) -> str:
    field = (match_field or "merchant").strip().lower()
    if field == "merchant":
        return _casefold_join(_merchant_context(expense, alias_map))
    if field in {"raw_text", "raw"}:
        return ocr_text.casefold()
    # "any" or unrecognized → match against merchant + ocr text + note
    return _casefold_join(
        [*_merchant_context(expense, alias_map), ocr_text, expense.note or ""]
    )


def _updated_at_matches(value):
    if value is None:
        return Expense.updated_at.is_(None)
    return Expense.updated_at == value


def _changed_after_rule_application(expense: Expense, change: RuleApplicationChange) -> bool:
    if expense.updated_at is None or change.created_at is None:
        return False
    return expense.updated_at > change.created_at


def _try_apply_rule_category(
    db: Session,
    *,
    tenant_id: str,
    status: str,
    expense: Expense,
    rule: CategoryRule,
    before_category: str,
    after_category: str,
    now,
) -> tuple[int, int, str, str, str] | None:
    result = db.execute(
        update(Expense)
        .where(ledger_filter(Expense, tenant_id))
        .where(Expense.id == expense.id)
        .where(Expense.status == status)
        .where(_auto_fillable_category_filter())
        .where(_updated_at_matches(expense.updated_at))
        .values(
            category=after_category,
            ocr_draft_fields=ocr_draft_fields_after_clearing(expense, {"category"}),
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        return None
    return (int(expense.id), int(rule.id), rule.keyword, before_category, after_category)


def _try_rollback_rule_change(
    db: Session,
    *,
    tenant_id: str,
    expense: Expense,
    change: RuleApplicationChange,
    now,
) -> bool:
    result = db.execute(
        update(Expense)
        .where(ledger_filter(Expense, tenant_id))
        .where(Expense.id == change.expense_id)
        .where(Expense.category == expense.category)
        .where(_updated_at_matches(expense.updated_at))
        .values(category=change.before_category, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def _matching_rule_category(
    expense: Expense,
    rules: list[CategoryRule],
    alias_map: dict[str, str],
    *,
    ocr_text: str = "",
) -> tuple[CategoryRule, str] | None:
    haystack = _haystack_for(expense, "any", alias_map, ocr_text=ocr_text)
    if not haystack:
        return None
    for rule in rules:
        if rule.keyword.casefold() in haystack and _rule_conditions_match(expense, rule):
            category = normalize_category(rule.category)
            if category:
                return rule, category
            return None
    return None
