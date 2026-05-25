"""Preview-only public API + shared _preview_apply_rules_to_status helper.

All functions in this module are pure reads — no DB mutations.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import CategoryRule, Expense
from app.services.category_service import normalize_category
from app.services.merchant_alias_service import enabled_merchant_alias_map
from app.services.rule_application_service._common import (
    _clamp_rule_application_scan_limit,
    _haystack_for,
    _matching_rule_category,
    _non_auto_fillable_category_count,
    _ocr_text_by_expense_id,
    _rule_application_candidates,
    _rule_application_preview_token,
)


def preview_rule_for_pending(
    db: Session,
    *,
    tenant_id: str,
    keyword: str,
    target_category: str | None,
    match_field: str = "merchant",
    limit: int = 10,
) -> tuple[int, list[dict]]:
    """Return (matched_count, items) for keyword match over pending expenses.

    Pure preview — does **not** mutate database. Only scans pending records.
    """
    keyword_clean = (keyword or "").strip()
    if not keyword_clean:
        raise AppError("invalid_request", status_code=422)
    needle = keyword_clean.casefold()
    field = (match_field or "merchant").strip().lower()
    field_label = {"merchant": "商家", "raw_text": "原文", "any": "原文/备注/商家"}.get(
        (match_field or "merchant").strip().lower(), "商家"
    )
    suggested = normalize_category(target_category) if target_category else None

    pending_rows = db.scalars(
        ledger_scoped_select(Expense, tenant_id)
        .where(Expense.status == "pending")
        .order_by(Expense.created_at.desc(), Expense.id.desc())
    )
    alias_map = enabled_merchant_alias_map(db, tenant_id=tenant_id)
    if field == "merchant":
        pending = pending_rows
        ocr_text_by_id: dict[int, str] = {}
    else:
        pending = list(pending_rows)
        ocr_text_by_id = _ocr_text_by_expense_id(
            db, tenant_id=tenant_id, expenses=pending
        )
    matched: list[dict] = []
    matched_count = 0
    capped = max(1, min(int(limit or 10), 50))
    for expense in pending:
        if needle not in _haystack_for(
            expense,
            match_field,
            alias_map,
            ocr_text=ocr_text_by_id.get(int(expense.id), ""),
        ):
            continue
        matched_count += 1
        if len(matched) >= capped:
            continue
        matched.append(
            {
                "id": expense.id,
                "merchant": expense.merchant,
                "amount_cents": expense.amount_cents,
                "current_category": normalize_category(expense.category or "其他"),
                "suggested_category": suggested,
                "reason": f"{field_label}包含 {keyword_clean}",
            }
        )
    return matched_count, matched


def preview_apply_rules_to_pending(
    db: Session,
    *,
    tenant_id: str,
    limit: int = 20,
    max_scan: int | None = None,
) -> dict:
    return _preview_apply_rules_to_status(
        db,
        tenant_id=tenant_id,
        status="pending",
        limit=limit,
        max_scan=max_scan,
    )


def preview_apply_rules_to_confirmed(
    db: Session,
    *,
    tenant_id: str,
    limit: int = 20,
    max_scan: int | None = None,
) -> dict:
    return _preview_apply_rules_to_status(
        db,
        tenant_id=tenant_id,
        status="confirmed",
        limit=limit,
        max_scan=max_scan,
    )


def validate_rule_application_preview(
    db: Session,
    *,
    tenant_id: str,
    status: str,
    preview_token: str | None,
    max_scan: int | None = None,
) -> dict:
    if not preview_token:
        raise AppError(
            "preview_required",
            "请先预览影响范围，再确认应用规则。",
            status_code=409,
        )
    if status == "pending":
        current_preview = preview_apply_rules_to_pending(
            db,
            tenant_id=tenant_id,
            limit=1,
            max_scan=max_scan,
        )
    elif status == "confirmed":
        current_preview = preview_apply_rules_to_confirmed(
            db,
            tenant_id=tenant_id,
            limit=1,
            max_scan=max_scan,
        )
    else:
        raise AppError("invalid_request", status_code=422)
    if current_preview["preview_token"] != preview_token:
        raise AppError(
            "preview_stale",
            "预览已过期，请重新预览后再确认。",
            status_code=409,
        )
    return current_preview


def _preview_apply_rules_to_status(
    db: Session,
    *,
    tenant_id: str,
    status: str,
    limit: int,
    max_scan: int | None,
) -> dict:
    expenses, scan_limit_reached = _rule_application_candidates(
        db,
        tenant_id=tenant_id,
        status=status,
        max_scan=max_scan,
    )
    rules = list(
        db.scalars(
            ledger_scoped_select(CategoryRule, tenant_id)
            .where(CategoryRule.enabled == True)  # noqa: E712
            .order_by(CategoryRule.priority.asc(), CategoryRule.id.asc())
        )
    )
    alias_map = enabled_merchant_alias_map(db, tenant_id=tenant_id)
    ocr_text_by_id = _ocr_text_by_expense_id(
        db, tenant_id=tenant_id, expenses=expenses
    )
    capped = max(1, min(int(limit or 20), 50))

    changed_count = 0
    skipped_non_default_category = _non_auto_fillable_category_count(
        db,
        tenant_id=tenant_id,
        status=status,
    )
    no_match_count = 0
    unchanged_count = 0
    items: list[dict] = []
    for expense in expenses:
        current_category = normalize_category(expense.category or "其他")
        match = _matching_rule_category(
            expense,
            rules,
            alias_map,
            ocr_text=ocr_text_by_id.get(int(expense.id), ""),
        )
        if match is None:
            no_match_count += 1
            continue
        rule, suggested_category = match
        if suggested_category == current_category:
            unchanged_count += 1
            continue
        changed_count += 1
        if len(items) >= capped:
            continue
        items.append(
            {
                "id": expense.id,
                "merchant": expense.merchant,
                "current_category": current_category,
                "suggested_category": suggested_category,
                "rule_keyword": rule.keyword,
                "reason": f"规则[{rule.keyword}] 将分类改为 {suggested_category}",
            }
        )

    return {
        "scanned": len(expenses),
        "pending_scanned": len(expenses),
        "confirmed_scanned": len(expenses),
        "changed_count": changed_count,
        "items": items,
        "skipped_non_default_category": skipped_non_default_category,
        "no_match_count": no_match_count,
        "unchanged_count": unchanged_count,
        "conflict_count": 0,
        "scan_limit_reached": scan_limit_reached,
        "scan_limit": _clamp_rule_application_scan_limit(max_scan),
        "preview_token": _rule_application_preview_token(
            status=status,
            max_scan=max_scan,
            expenses=expenses,
            rules=rules,
            alias_map=alias_map,
            ocr_text_by_id=ocr_text_by_id,
        ),
    }
