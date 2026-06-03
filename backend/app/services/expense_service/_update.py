"""Update / lifecycle: field edits, batch updates, confirm, reject, undo-reject."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Expense
from app.schemas import (
    ConfirmedExpenseBatchUpdateRequest,
    ConfirmedExpenseBatchUpdateResponse,
    ExpenseUpdateRequest,
)
from app.services.bill_split_service import assert_no_immutable_field_changes
from app.services.classify_service import classify_expense
from app.services.cleanup_service import cleanup_after_confirm
from app.services.duplicate_service import (
    clear_duplicate_references_to,
    mark_duplicate_status,
    revalidate_duplicate_references_to,
)
from app.services.exchange_rate_service import apply_currency_payload, refresh_currency_snapshot
from app.services.expense_service._helpers import (
    EDITABLE_STATUSES,
    _clean_category,
    _clean_optional_text,
    _clean_text,
    _ensure_expense_can_confirm,
    _expense_has_pending_fx,
)
from app.services.expense_service._query import get_expense
from app.services.ocr_service import clear_ocr_draft_fields
from app.services.optimistic_concurrency import claim_row_with_token
from app.services.receipt_item_service import recompute_items_sum_status
from app.services.resource_audit import record_resource_action
from app.services.soft_delete_policy import SOFT_DELETE_RETENTION
from app.services.tag_service import normalize_tags, sync_expense_tags
from app.services.time_service import ensure_utc, now_utc

__all__ = [
    "batch_update_confirmed_expenses",
    "confirm_expense",
    "reject_expense",
    "undo_reject_expense",
    "update_expense",
]


def batch_update_confirmed_expenses(
    db: Session,
    *,
    tenant_id: str,
    payload: ConfirmedExpenseBatchUpdateRequest,
) -> ConfirmedExpenseBatchUpdateResponse:
    expense_ids = list(dict.fromkeys(payload.expense_ids))
    expected_by_id = payload.expected_row_version_by_id
    if set(expected_by_id) != set(expense_ids):
        raise AppError("invalid_request", status_code=422)

    category_provided = payload.category is not None
    tags_provided = payload.tags is not None
    if not category_provided and not tags_provided:
        raise AppError("invalid_request", status_code=422)

    category = payload.category.strip() if category_provided else None
    if category_provided and not category:
        raise AppError("invalid_request", status_code=422)

    normalized_tags = normalize_tags(payload.tags) if tags_provided else None
    rows = list(
        db.scalars(
            select(Expense)
            .where(Expense.tenant_id == tenant_id)
            .where(Expense.id.in_(expense_ids))
        )
    )
    rows_by_id = {row.id: row for row in rows}

    updated_count = 0
    skipped_not_found = 0
    skipped_not_confirmed = 0
    now = now_utc()
    for expense_id in expense_ids:
        expense = rows_by_id.get(expense_id)
        if expense is None:
            skipped_not_found += 1
            continue
        if expense.status != "confirmed":
            skipped_not_confirmed += 1
            continue
        rowcount = claim_row_with_token(
            db,
            Expense,
            pk_id=expense_id,
            tenant_id=tenant_id,
            expected_row_version=expected_by_id[expense_id],
            set_values={"updated_at": now},
            extra_where=(Expense.status == "confirmed",),
            synchronize_session=False,
        )
        if rowcount != 1:
            db.rollback()
            raise AppError("state_conflict", status_code=409)
        if category_provided:
            expense.category = _clean_category(category)
        if tags_provided:
            expense.tags = normalized_tags
            sync_expense_tags(db, expense)
        expense.updated_at = now
        updated_count += 1

    if updated_count:
        db.commit()

    return ConfirmedExpenseBatchUpdateResponse(
        requested_count=len(expense_ids),
        updated_count=updated_count,
        skipped_not_found=skipped_not_found,
        skipped_not_confirmed=skipped_not_confirmed,
    )


def _claim_expense_for_update(
    db: Session,
    *,
    expense_id: int,
    tenant_id: str,
    expected_row_version: int,
    claimed_at: datetime,
) -> Expense:
    """ADR-0038 atomic optimistic-concurrency claim for ``PATCH /api/expenses/{id}``.

    Atomically sets ``updated_at = claimed_at`` only when the row's
    ``(id, tenant_id, status ∈ EDITABLE_STATUSES, updated_at)``
    matches the client's snapshot. ``rowcount == 0`` disambiguates:
    missing / non-editable row → ``expense_not_found`` 404; else →
    ``state_conflict`` 409. The claim becomes part of the same
    transaction the business-logic updates commit, so stale writes
    never reach the row.

    tz normalisation lives in ``optimistic_concurrency.row_version_predicate``.
    """
    rowcount = claim_row_with_token(
        db,
        Expense,
        pk_id=expense_id,
        tenant_id=tenant_id,
        expected_row_version=expected_row_version,
        set_values={"updated_at": claimed_at},
        extra_where=(Expense.status.in_(EDITABLE_STATUSES),),
        synchronize_session=False,
    )
    if rowcount != 1:
        db.expire_all()
        current = db.scalar(
            ledger_scoped_select(Expense, tenant_id).where(Expense.id == expense_id)
        )
        if current is None or current.status not in EDITABLE_STATUSES:
            raise AppError("expense_not_found", status_code=404)
        raise AppError("state_conflict", status_code=409)
    db.expire_all()
    return get_expense(db, expense_id, tenant_id)


def update_expense(
    db: Session,
    expense_id: int,
    tenant_id: str,
    payload: ExpenseUpdateRequest,
    *,
    commit: bool = True,
) -> Expense:
    # ADR-0038: atomic UPDATE WHERE id, tenant_id, status, updated_at =
    # expected. Race-rejected at the DB layer (rowcount=0 → 404/409),
    # so two clients that both read the same updated_at can't both
    # silently overwrite the row.
    #
    # ADR-0042 §4.5: ``commit=False`` lets the idempotent PATCH route fold the
    # idempotency-key claim, this OCC claim + field edits, and the
    # ``mark_idempotency_succeeded`` flip into a SINGLE ``db.commit()`` — so
    # "mutation committed but key not recorded" (and the inverse) can't happen.
    # The other 3 callers (/web edit, category recat, pending-review bulk) keep
    # the default and commit per-row.
    expense = _claim_expense_for_update(
        db,
        expense_id=expense_id,
        tenant_id=tenant_id,
        expected_row_version=payload.expected_row_version,
        claimed_at=now_utc(),
    )

    updates = payload.model_dump(
        exclude_unset=True, exclude={"expected_row_version"}
    )

    # ADR-0029: received split expenses freeze their money / merchant /
    # time fields — those represent the agreed-upon debt with the sender
    # and silently mutating them after accept is a data-integrity issue.
    assert_no_immutable_field_changes(expense, set(updates.keys()))

    if "merchant" in updates:
        expense.merchant = _clean_optional_text(updates["merchant"])
    if "category" in updates and updates["category"]:
        expense.category = _clean_category(updates["category"])
    if "note" in updates:
        expense.note = _clean_text(updates["note"])
    if "spent_at" in updates:
        expense.expense_time = ensure_utc(updates["spent_at"])
    elif "expense_time" in updates:
        expense.expense_time = ensure_utc(updates["expense_time"])
    if "tags" in updates:
        expense.tags = normalize_tags(updates["tags"])
    if "value_score" in updates:
        expense.value_score = updates["value_score"]
    if "regret_score" in updates:
        expense.regret_score = updates["regret_score"]
    apply_currency_payload(
        db,
        tenant_id=tenant_id,
        expense=expense,
        payload=payload,
        amount_was_explicit="amount_cents" in updates,
    )
    if expense.status == "confirmed":
        _ensure_expense_can_confirm(expense)

    clear_ocr_draft_fields(expense, list(updates.keys()))

    should_auto_classify = (
        "category" not in updates
        and expense.category == "其他"
        and any(field in updates for field in {"merchant", "note"})
    )
    if should_auto_classify:
        classify_expense(db, expense)

    if any(
        field in updates
        for field in {
            "amount_cents",
            "original_currency",
            "original_amount",
            "original_currency_code",
            "original_amount_minor",
            "exchange_rate_date",
            "merchant",
            "spent_at",
            "expense_time",
        }
    ):
        mark_duplicate_status(db, expense)
        db.flush()
        revalidate_duplicate_references_to(db, tenant_id=tenant_id, duplicate_of_id=expense.id)
    if "tags" in updates:
        sync_expense_tags(db, expense)

    # 0035: amount_cents 改动后必须重算 items_sum_status。
    if "amount_cents" in updates:
        recompute_items_sum_status(db, expense)

    expense.updated_at = now_utc()
    if commit:
        db.commit()
        db.refresh(expense)
    else:
        # Caller (idempotent PATCH route) owns the commit: it still needs the
        # edits flushed so a follow-on read in the same transaction sees them.
        db.flush()
    return expense


def confirm_expense(
    db: Session,
    expense_id: int,
    tenant_id: str,
    *,
    expected_row_version: int,
) -> Expense:
    """ADR-0038 PR-2b: confirm with optimistic concurrency.

    Idempotency on terminal states is preserved: confirming an already
    ``confirmed`` row returns 200 without inspecting the token. Stale
    snapshot against a still-``pending`` row → 409 ``state_conflict``
    via DB-level ``updated_at = expected`` predicate.
    """
    expense = get_expense(db, expense_id, tenant_id)
    if expense.status == "confirmed":
        return expense
    if expense.status != "pending":
        raise AppError("expense_not_found", status_code=404)
    if _expense_has_pending_fx(expense):
        refresh_currency_snapshot(db, tenant_id=tenant_id, expense=expense)
    _ensure_expense_can_confirm(expense)
    db.flush()

    now = now_utc()
    rowcount = claim_row_with_token(
        db,
        Expense,
        pk_id=expense_id,
        tenant_id=tenant_id,
        expected_row_version=expected_row_version,
        set_values={"status": "confirmed", "confirmed_at": now, "updated_at": now},
        extra_where=(Expense.status == "pending", Expense.amount_cents.is_not(None)),
        synchronize_session=False,
    )
    if rowcount != 1:
        db.expire_all()
        expense = get_expense(db, expense_id, tenant_id)
        if expense.status == "confirmed":
            return expense
        if expense.status == "pending":
            # row is still pending; either amount_cents missing (terminal
            # validation error) or updated_at mismatched. Validation
            # raises its own error; otherwise stale → 409.
            _ensure_expense_can_confirm(expense)
            raise AppError("state_conflict", status_code=409)
        raise AppError("expense_not_found", status_code=404)

    db.expire_all()
    expense = get_expense(db, expense_id, tenant_id)
    sync_expense_tags(db, expense)
    # v1.2 ops: close any active algorithm_decisions attached to this
    # expense — confirmation means no UI will surface them again.
    from app.services.learning_service import close_active_decisions_for_subject

    close_active_decisions_for_subject(
        db,
        tenant_id=tenant_id,
        subject_kind="expense",
        subject_id=expense.id,
    )
    db.commit()
    db.refresh(expense)
    if cleanup_after_confirm(expense):
        db.commit()
        db.refresh(expense)
    return expense


def reject_expense(
    db: Session,
    expense_id: int,
    tenant_id: str,
    *,
    expected_row_version: int,
) -> Expense:
    """ADR-0038 PR-2b: reject with optimistic concurrency.

    Like ``confirm_expense``, idempotent on ``rejected`` (terminal) and
    409 on stale ``pending`` rows.
    """
    now = now_utc()
    rowcount = claim_row_with_token(
        db,
        Expense,
        pk_id=expense_id,
        tenant_id=tenant_id,
        expected_row_version=expected_row_version,
        set_values={"status": "rejected", "rejected_at": now, "updated_at": now},
        extra_where=(Expense.status == "pending",),
        synchronize_session=False,
    )
    if rowcount != 1:
        db.expire_all()
        existing = get_expense(db, expense_id, tenant_id)
        if existing.status == "rejected":
            return existing
        if existing.status == "pending":
            raise AppError("state_conflict", status_code=409)
        raise AppError("expense_not_found", status_code=404)

    db.expire_all()
    expense = get_expense(db, expense_id, tenant_id)
    clear_duplicate_references_to(db, tenant_id=tenant_id, duplicate_of_id=expense.id)
    # v1.2 ops: rejected → no UI shows suggestions for this expense
    # again either; close them.
    from app.services.learning_service import close_active_decisions_for_subject

    close_active_decisions_for_subject(
        db,
        tenant_id=tenant_id,
        subject_kind="expense",
        subject_id=expense.id,
    )
    db.commit()
    db.refresh(expense)
    return expense


def undo_reject_expense(
    db: Session,
    expense_id: int,
    tenant_id: str,
    expected_row_version: int,
    *,
    actor_account_id: int | None = None,
) -> Expense:
    """ADR-0038 undo: restore a recently-rejected expense within retention window.

    Atomic ``UPDATE WHERE id, tenant_id, status='rejected',
    rejected_at >= cutoff, updated_at = expected_row_version`` + ``rowcount=1``
    判定避免 SELECT-then-write race(memory feedback_adr_implementation
    _atomicity)。rowcount=0 → 404 (already restored / never rejected /
    past 5min window / cross-tenant / **stale undo for a row that's been
    re-rejected since the banner was shown**).

    The OCC token (expected_row_version) is the v1.3 PR-A addition. Without
    it, a stale /undo request from a cached banner could un-do a NEW reject
    the user just made: T0 reject A → T+3s undo → T+10s re-reject A (this
    time intentionally) → T+15s stale /undo arrives → server sees
    status='rejected' AND rejected_at>=cutoff and undoes the **second**
    reject (the intentional one). The token-check rejects this because A's
    updated_at was bumped by the second reject.

    Restore values: ``status='pending'`` (回到 reject 前最普通的可编辑状态)
    + ``rejected_at = NULL`` (复用 reject lifecycle 的 nullable 语义) +
    ``updated_at = now`` (让任何持有 pre-undo token 的 mutate 撞 409
    state_conflict, 防 stale write)。

    Appends ``ledger_audit_logs action='undo'``, resource_type='expense',
    resource_public_id = expense.public_id。和 merchant_alias undo /
    category_rule undo 同 pattern。

    **Current /undo contract for child resources (v1.x temporary —
    replaced by ADR-0040 when landed)**: undo ONLY flips the parent
    Expense row's status / rejected_at / updated_at. Splits, items, and
    suggestion decisions on this expense are NOT touched. After undo,
    child resources retain whatever state they had during reject. This
    is explicit deterministic behavior, not undefined — but the full
    semantic (e.g. should bill_split invitations re-activate? should
    item-level acknowledge-mismatch persist?) is owned by ADR-0040.

    **ABA (resolved, ADR-0041)**: the CAS token here is the monotonic
    ``row_version`` int (``WHERE row_version = expected``), which strictly
    increments per guarded UPDATE. This closes the old ``updated_at`` ABA
    window — two operations within ~15ms could write equal ``updated_at``
    values and defeat the OCC check; an integer that only ever goes up can't.
    """
    now = now_utc()
    cutoff = now - SOFT_DELETE_RETENTION
    stmt = (
        update(Expense)
        .where(Expense.id == expense_id)
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.status == "rejected")
        .where(Expense.rejected_at.is_not(None))
        .where(Expense.rejected_at >= cutoff)
        .where(Expense.row_version == expected_row_version)
        .values(
            status="pending",
            rejected_at=None,
            updated_at=now,
            row_version=Expense.row_version + 1,
        )
    )
    result = db.execute(stmt)
    if result.rowcount != 1:
        # 不区分 not_found / past_window / never_rejected / stale_token:
        # 四种状态下 row 都不再 undo-able,暴露区别给客户端 = 暴露 ledger
        # 内部状态 + 也无法给用户决策 (无论哪种原因, 都得让用户重新看一眼
        # 最新状态)。OCC stale_token 走同一 404 而不是 409 是因为在 retention
        # 窗口外/外 tenant 等场景下区分意义不大,统一 404 = "refetch 最新状态"。
        db.rollback()
        raise AppError("expense_not_found", status_code=404)
    db.expire_all()
    expense = get_expense(db, expense_id, tenant_id)
    record_resource_action(
        db,
        ledger_id=tenant_id,
        action="undo",
        resource_type="expense",
        resource_public_id=expense.public_id,
        actor_account_id=actor_account_id,
    )
    db.commit()
    db.refresh(expense)
    return expense
