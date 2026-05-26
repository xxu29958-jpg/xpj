"""Bulk-action service for /web/pending review.

Extracted from ``web_pending.web_review_bulk`` (the 120-line dispatcher
flagged in the v1.0 maturity audit as "route too thick") so the route
stays HTTP-wiring-only:

- Action dispatch (set_category / set_merchant / reject / confirm_ready
  / keep_duplicate) and the per-row skip-reason classification both
  live here.
- Pre-flight validation (unknown action, missing category/merchant
  payload) raises ``AppError`` — the route turns those into a redirect
  with the user-facing message.
- Cross-ledger ids are accounted for in ``skipped_reasons["不属于当前账本"]``;
  caller gets one structured ``BulkResult`` and only has to format it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.errors import AppError
from app.schemas import ExpenseUpdateRequest
from app.services.expense_service import (
    confirm_expense,
    list_expenses_by_ids,
    mark_expense_not_duplicate,
    reject_expense,
    update_expense,
)

ALLOWED_ACTIONS = frozenset(
    {"set_category", "set_merchant", "reject", "confirm_ready", "keep_duplicate"}
)

SKIP_REASON_CROSS_LEDGER = "不属于当前账本"
SKIP_REASON_NOT_PENDING = "非待确认"
SKIP_REASON_MISSING_AMOUNT = "缺金额"
SKIP_REASON_NOT_SUSPECTED_DUPLICATE = "非疑似重复"


@dataclass
class BulkResult:
    success_count: int = 0
    skipped_reasons: dict[str, int] = field(default_factory=dict)

    def bump(self, label: str) -> None:
        self.skipped_reasons[label] = self.skipped_reasons.get(label, 0) + 1


def apply_review_bulk(
    db: Session,
    *,
    tenant_id: str,
    action: str,
    expense_ids: list[int],
    category: str = "",
    merchant: str = "",
) -> BulkResult:
    """Run a bulk-review action and return success/skip counters.

    Raises ``AppError("invalid_request", ...)`` when the payload itself is
    rejected (unknown action, empty category/merchant for the two
    metadata-edit actions). Per-row failures are captured in
    ``skipped_reasons``, never raised.
    """
    if action not in ALLOWED_ACTIONS:
        raise AppError("invalid_request", status_code=422)

    category_clean = category.strip()
    merchant_clean = merchant.strip()

    if action == "set_category" and not category_clean:
        raise AppError("invalid_request", "请填写分类。", status_code=422)
    if action == "set_merchant" and not merchant_clean:
        raise AppError("invalid_request", "请填写商家。", status_code=422)

    rows = list_expenses_by_ids(db, tenant_id=tenant_id, expense_ids=expense_ids)
    found_ids = {row.id for row in rows}

    result = BulkResult()
    cross_ledger = sum(1 for eid in expense_ids if eid not in found_ids)
    if cross_ledger:
        result.skipped_reasons[SKIP_REASON_CROSS_LEDGER] = cross_ledger

    # Resolve action handler once outside the loop so the per-row body
    # is a flat dispatcher (audit A5 used to flag this function at
    # nesting depth 6 because the if/elif chain compiles to a nested
    # ``If(orelse=[If(...)])`` tree).
    handler = _resolve_bulk_action_handler(
        action, category_clean=category_clean, merchant_clean=merchant_clean
    )
    for row in rows:
        handler(db, row, tenant_id, result)
    return result


def _resolve_bulk_action_handler(
    action: str, *, category_clean: str, merchant_clean: str
):
    """Return a ``(db, row, tenant_id, result) -> None`` callable.

    ``action`` is trusted because the caller already enforced
    ``ALLOWED_ACTIONS`` membership; cross-ledger / not-pending checks
    happen inside the leaf handlers.
    """
    if action == "set_category":
        return lambda db, row, tenant_id, result: _apply_metadata_update(
            db,
            row,
            tenant_id,
            ExpenseUpdateRequest(
                category=category_clean,
                # ADR-0038 PR-2a: 服务端 bulk handler 已经读到 row.updated_at，
                # 拿来当 expected_updated_at 用即可，无需让外层管线携带 token。
                expected_updated_at=row.updated_at,
            ),
            result,
        )
    if action == "set_merchant":
        return lambda db, row, tenant_id, result: _apply_metadata_update(
            db,
            row,
            tenant_id,
            ExpenseUpdateRequest(
                merchant=merchant_clean,
                expected_updated_at=row.updated_at,
            ),
            result,
        )
    if action == "reject":
        return _apply_reject
    if action == "confirm_ready":
        return _apply_confirm_ready
    return _apply_keep_duplicate


def _apply_metadata_update(
    db: Session,
    row,
    tenant_id: str,
    payload: ExpenseUpdateRequest,
    result: BulkResult,
) -> None:
    if row.status != "pending":
        result.bump(SKIP_REASON_NOT_PENDING)
        return
    try:
        update_expense(db, row.id, tenant_id, payload)
        result.success_count += 1
    except AppError:
        result.bump("更新失败")


def _apply_reject(db: Session, row, tenant_id: str, result: BulkResult) -> None:
    if row.status != "pending":
        result.bump(SKIP_REASON_NOT_PENDING)
        return
    try:
        # ADR-0038 PR-2b: 服务端 bulk handler 已经读到 row.updated_at，
        # 直接喂给 reject_expense；不让外层管线携带 token。
        reject_expense(db, row.id, tenant_id, expected_updated_at=row.updated_at)
        result.success_count += 1
    except AppError:
        result.bump("忽略失败")


def _apply_confirm_ready(db: Session, row, tenant_id: str, result: BulkResult) -> None:
    if row.status != "pending":
        result.bump(SKIP_REASON_NOT_PENDING)
        return
    if row.amount_cents is None:
        result.bump(SKIP_REASON_MISSING_AMOUNT)
        return
    try:
        confirm_expense(db, row.id, tenant_id, expected_updated_at=row.updated_at)
        result.success_count += 1
    except AppError:
        result.bump("确认失败")


def _apply_keep_duplicate(db: Session, row, tenant_id: str, result: BulkResult) -> None:
    if (row.duplicate_status or "") != "suspected":
        result.bump(SKIP_REASON_NOT_SUSPECTED_DUPLICATE)
        return
    try:
        mark_expense_not_duplicate(
            db, row.id, tenant_id, expected_updated_at=row.updated_at
        )
        result.success_count += 1
    except AppError:
        result.bump("更新失败")
