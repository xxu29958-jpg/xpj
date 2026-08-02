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

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.schemas import ExpenseUpdateRequest
from app.services.data_quality_service import (
    is_ready_to_confirm_row,
    is_uncategorized_expense_category,
    is_usable_pending_merchant,
)
from app.services.duplicate_service import clear_duplicate_references_to
from app.services.expense_service import (
    confirm_expense,
    list_expenses_by_ids,
    mark_expense_not_duplicate,
    reject_expense,
    update_expense,
)

ALLOWED_ACTIONS = frozenset({"set_category", "set_merchant", "reject", "confirm_ready", "keep_duplicate"})

SKIP_REASON_CROSS_LEDGER = "不属于当前账本"
SKIP_REASON_NOT_PENDING = "非待确认"
SKIP_REASON_MISSING_AMOUNT = "缺金额"
SKIP_REASON_MISSING_MERCHANT = "缺商家"
SKIP_REASON_MISSING_CATEGORY = "缺分类"
SKIP_REASON_SUSPECTED_DUPLICATE = "疑似重复待裁决"
SKIP_REASON_FX_PENDING = "待汇率就绪"
SKIP_REASON_NOT_SUSPECTED_DUPLICATE = "非疑似重复"
SKIP_REASON_STALE = "页面内容已变化，请刷新后重新选择"


@dataclass
class BulkResult:
    # issue #64 W3: track WHICH rows were actioned, not just how many. The
    # fetch+partial /web bulk bar splices exactly these rows out of the DOM —
    # confirm_ready skips non-ready rows, so a count alone can't tell the client
    # which of the selected rows actually left the pending list.
    success_ids: list[int] = field(default_factory=list)
    skipped_reasons: dict[str, int] = field(default_factory=dict)
    undo_row_versions: dict[int, int] = field(default_factory=dict)

    @property
    def success_count(self) -> int:
        return len(self.success_ids)

    def record_success(self, row_id: int, *, undo_row_version: int | None = None) -> None:
        self.success_ids.append(row_id)
        if undo_row_version is not None:
            self.undo_row_versions[row_id] = undo_row_version

    def bump(self, label: str) -> None:
        self.skipped_reasons[label] = self.skipped_reasons.get(label, 0) + 1


def apply_review_bulk(
    db: Session,
    *,
    tenant_id: str,
    action: str,
    expense_ids: list[int],
    expected_row_version_by_id: dict[int, int],
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

    unique_expense_ids = list(dict.fromkeys(expense_ids))
    if set(expected_row_version_by_id) != set(unique_expense_ids):
        raise AppError(
            "invalid_request",
            "页面已过期，请刷新后重新操作。",
            status_code=422,
        )

    category_clean = category.strip()
    merchant_clean = merchant.strip()

    if action == "set_category" and not category_clean:
        raise AppError("invalid_request", "请填写分类。", status_code=422)
    if action == "set_merchant" and not merchant_clean:
        raise AppError("invalid_request", "请填写商家。", status_code=422)

    rows = list_expenses_by_ids(db, tenant_id=tenant_id, expense_ids=unique_expense_ids)
    rows_by_id = {row.id: row for row in rows}

    result = BulkResult()
    cross_ledger = sum(1 for eid in unique_expense_ids if eid not in rows_by_id)
    if cross_ledger:
        result.skipped_reasons[SKIP_REASON_CROSS_LEDGER] = cross_ledger

    # Resolve action handler once outside the loop so the per-row body
    # is a flat dispatcher (audit A5 used to flag this function at
    # nesting depth 6 because the if/elif chain compiles to a nested
    # ``If(orelse=[If(...)])`` tree).
    handler = _resolve_bulk_action_handler(action, category_clean=category_clean, merchant_clean=merchant_clean)
    try:
        for expense_id in unique_expense_ids:
            row = rows_by_id.get(expense_id)
            if row is None:
                continue
            expected_row_version = expected_row_version_by_id[expense_id]
            if row.row_version != expected_row_version:
                result.bump(SKIP_REASON_STALE)
                continue
            handler(db, row, tenant_id, expected_row_version, result)

        if action == "reject" and result.success_ids:
            # A selected row may itself reference another selected row as a
            # suspected duplicate. Clearing that reference after rejecting the
            # first row would otherwise advance the second row's OCC token and
            # make this command reject its own still-valid page snapshot. Mark
            # every successful selection terminal first, then clear references:
            # rejected rows are excluded, while surviving dependants still get
            # the required row-version bump. Commit the whole bulk command once.
            for expense_id in result.success_ids:
                clear_duplicate_references_to(
                    db,
                    tenant_id=tenant_id,
                    duplicate_of_id=expense_id,
                )
            db.commit()
    except SQLAlchemyError:
        if action == "reject":
            db.rollback()
        raise
    return result


def _resolve_bulk_action_handler(action: str, *, category_clean: str, merchant_clean: str):
    """Return a ``(db, row, tenant_id, expected_row_version, result)`` callable.

    ``action`` is trusted because the caller already enforced
    ``ALLOWED_ACTIONS`` membership; cross-ledger / not-pending checks
    happen inside the leaf handlers.
    """
    if action == "set_category":
        return lambda db, row, tenant_id, expected_row_version, result: _apply_metadata_update(
            db,
            row,
            tenant_id,
            ExpenseUpdateRequest(
                category=category_clean,
                expected_row_version=expected_row_version,
            ),
            result,
        )
    if action == "set_merchant":
        return lambda db, row, tenant_id, expected_row_version, result: _apply_metadata_update(
            db,
            row,
            tenant_id,
            ExpenseUpdateRequest(
                merchant=merchant_clean,
                expected_row_version=expected_row_version,
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
        result.record_success(row.id)
    except AppError as exc:
        _record_action_error(result, exc, fallback="更新失败")


def _apply_reject(
    db: Session,
    row,
    tenant_id: str,
    expected_row_version: int,
    result: BulkResult,
) -> None:
    if row.status != "pending":
        result.bump(SKIP_REASON_NOT_PENDING)
        return
    try:
        rejected = reject_expense(
            db,
            row.id,
            tenant_id,
            expected_row_version=expected_row_version,
            commit=False,
            cleanup_duplicate_references=False,
        )
        result.record_success(row.id, undo_row_version=rejected.row_version)
    except AppError as exc:
        _record_action_error(result, exc, fallback="忽略失败")


def _apply_confirm_ready(
    db: Session,
    row,
    tenant_id: str,
    expected_row_version: int,
    result: BulkResult,
) -> None:
    if row.status != "pending":
        result.bump(SKIP_REASON_NOT_PENDING)
        return
    # Full ready caliber (218-B3 round 7): the bulk action targets exactly the
    # rows the ready filter/DQ link advertise — amount + usable merchant +
    # categorized + non-suspected + fx-ready, not just amount.
    if not is_ready_to_confirm_row(
        amount_cents=row.amount_cents,
        merchant=row.merchant,
        category=row.category,
        duplicate_status=row.duplicate_status,
        fx_status=row.fx_status,
    ):
        result.bump(_confirm_skip_reason(row))
        return
    try:
        confirm_expense(
            db,
            row.id,
            tenant_id,
            expected_row_version=expected_row_version,
        )
        result.record_success(row.id)
    except AppError as exc:
        _record_action_error(result, exc, fallback="确认失败")


def _confirm_skip_reason(row) -> str:
    """Per-dimension skip label for confirm_ready (same checks, in fix order)."""
    if row.amount_cents is None:
        return SKIP_REASON_MISSING_AMOUNT
    if not is_usable_pending_merchant(row.merchant):
        return SKIP_REASON_MISSING_MERCHANT
    if is_uncategorized_expense_category(row.category):
        return SKIP_REASON_MISSING_CATEGORY
    if (row.duplicate_status or "") == "suspected":
        return SKIP_REASON_SUSPECTED_DUPLICATE
    return SKIP_REASON_FX_PENDING


def _apply_keep_duplicate(
    db: Session,
    row,
    tenant_id: str,
    expected_row_version: int,
    result: BulkResult,
) -> None:
    if (row.duplicate_status or "") != "suspected":
        result.bump(SKIP_REASON_NOT_SUSPECTED_DUPLICATE)
        return
    try:
        mark_expense_not_duplicate(
            db,
            row.id,
            tenant_id,
            expected_row_version=expected_row_version,
        )
        result.record_success(row.id)
    except AppError as exc:
        _record_action_error(result, exc, fallback="更新失败")


def _record_action_error(result: BulkResult, exc: AppError, *, fallback: str) -> None:
    if exc.error == "state_conflict":
        result.bump(SKIP_REASON_STALE)
        return
    result.bump(fallback)
