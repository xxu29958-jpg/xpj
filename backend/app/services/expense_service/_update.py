"""Update / lifecycle: field edits, batch updates, confirm, reject, undo-reject."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, update
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Expense
from app.schemas import ExpenseUpdateRequest
from app.services.cleanup_service import cleanup_after_confirm
from app.services.currency_binding_service import (
    authorize_currency_metadata_write,
    resolve_write_capability,
)
from app.services.duplicate_service import clear_duplicate_references_to
from app.services.exchange_rate_service import refresh_currency_snapshot
from app.services.expense_revision_service import record_confirmation_revision
from app.services.expense_service._field_mutation import apply_expense_fields_to_claimed_row
from app.services.expense_service._helpers import (
    _ensure_pending_expense_can_confirm,
    _expense_has_pending_fx,
)
from app.services.expense_service._query import get_expense, resolve_expense
from app.services.expense_split_service import validate_current_expense_split_allocation
from app.services.optimistic_concurrency import claim_row_with_token
from app.services.resource_audit import record_resource_action
from app.services.soft_delete_policy import SOFT_DELETE_RETENTION
from app.services.tag_service import sync_expense_tags
from app.services.time_service import now_utc

__all__ = [
    "confirm_expense",
    "reject_expense",
    "undo_reject_expense",
    "update_expense",
]


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
    ``(id, tenant_id, status = pending, row_version)``
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
        extra_where=(Expense.status == "pending",),
        synchronize_session=False,
    )
    if rowcount != 1:
        db.expire_all()
        current = resolve_expense(db, tenant_id, expense_id)
        if current is None or current.status == "rejected":
            raise AppError("expense_not_found", status_code=404)
        if current.status == "confirmed":
            raise AppError("expense_correction_required", status_code=409)
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
    authorize_currency_metadata_write(db)
    expense = _claim_expense_for_update(
        db,
        expense_id=expense_id,
        tenant_id=tenant_id,
        expected_row_version=payload.expected_row_version,
        claimed_at=now_utc(),
    )
    amount_before = expense.amount_cents

    apply_expense_fields_to_claimed_row(
        db,
        expense=expense,
        tenant_id=tenant_id,
        payload=payload,
    )
    if expense.amount_cents != amount_before:
        validate_current_expense_split_allocation(db, expense=expense)

    if commit:
        db.commit()
        db.refresh(expense)
    else:
        # Caller (idempotent PATCH route) owns the commit: it still needs the
        # edits flushed so a follow-on read in the same transaction sees them.
        db.flush()
    return expense


def _claim_pending_confirmation(
    db: Session,
    *,
    expense_id: int,
    tenant_id: str,
    expected_row_version: int,
) -> tuple[Expense, bool]:
    expense = get_expense(db, expense_id, tenant_id)
    if expense.status == "confirmed":
        return expense, False
    if expense.status != "pending":
        raise AppError("expense_not_found", status_code=404)
    if _expense_has_pending_fx(expense):
        refresh_currency_snapshot(db, tenant_id=tenant_id, expense=expense)
    _ensure_pending_expense_can_confirm(expense)
    validate_current_expense_split_allocation(db, expense=expense)
    db.flush()
    now = now_utc()
    claimed = claim_row_with_token(
        db,
        Expense,
        pk_id=expense_id,
        tenant_id=tenant_id,
        expected_row_version=expected_row_version,
        set_values={"status": "confirmed", "confirmed_at": now, "updated_at": now},
        extra_where=(Expense.status == "pending", Expense.amount_cents.is_not(None)),
        synchronize_session=False,
    )
    if claimed == 1:
        db.expire_all()
        return get_expense(db, expense_id, tenant_id), True
    db.expire_all()
    latest = get_expense(db, expense_id, tenant_id)
    if latest.status == "confirmed":
        return latest, False
    if latest.status == "pending":
        _ensure_pending_expense_can_confirm(latest)
        raise AppError("state_conflict", status_code=409)
    raise AppError("expense_not_found", status_code=404)


def _publish_confirmation(
    db: Session,
    expense: Expense,
    *,
    actor_account_id: int | None,
    actor_device_id: int | None,
    commit: bool,
) -> Expense:
    sync_expense_tags(db, expense)
    from app.services.learning_service import close_active_decisions_for_subject

    close_active_decisions_for_subject(
        db,
        tenant_id=expense.tenant_id,
        subject_kind="expense",
        subject_id=expense.id,
    )
    record_confirmation_revision(
        db,
        expense,
        actor_account_id=actor_account_id,
        actor_device_id=actor_device_id,
    )
    if not commit:
        db.flush()
        return expense
    db.commit()
    db.refresh(expense)
    if cleanup_after_confirm(db, expense):
        db.commit()
        db.refresh(expense)
    return expense


def confirm_expense(
    db: Session,
    expense_id: int,
    tenant_id: str,
    *,
    expected_row_version: int,
    actor_account_id: int | None = None,
    actor_device_id: int | None = None,
    commit: bool = True,
) -> Expense:
    """ADR-0038 PR-2b: confirm with optimistic concurrency.

    Idempotency on terminal states is preserved: confirming an already
    ``confirmed`` row returns 200 without inspecting the token. Stale
    snapshot against a still-``pending`` row → 409 ``state_conflict``
    via the DB-level ``row_version = expected`` predicate.

    ADR-0042: ``commit=False`` lets the idempotent confirm route fold the
    key claim + this status flip + ``mark_idempotency_succeeded`` into ONE
    commit (§4.5); the route then runs ``cleanup_after_confirm`` as the same
    post-confirm side-effect commit this method does internally when ``commit``.
    """
    resolve_write_capability(db)
    expense, newly_confirmed = _claim_pending_confirmation(
        db,
        expense_id=expense_id,
        tenant_id=tenant_id,
        expected_row_version=expected_row_version,
    )
    if not newly_confirmed:
        return expense
    if expense.status != "confirmed":
        raise AppError("server_error", status_code=500)
    return _publish_confirmation(
        db,
        expense,
        actor_account_id=actor_account_id,
        actor_device_id=actor_device_id,
        commit=commit,
    )


def reject_expense(
    db: Session,
    expense_id: int,
    tenant_id: str,
    *,
    expected_row_version: int,
    commit: bool = True,
    cleanup_duplicate_references: bool = True,
) -> Expense:
    """Reject with OCC; terminal rejected rows are idempotent. Stale writable
    rows fail with 409. ``commit=False`` lets the caller own the
    transaction, including any deferred duplicate-reference cleanup.
    """
    resolve_write_capability(db)
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
        if existing.status == "confirmed":
            raise AppError("expense_reversal_required", status_code=409)
        if existing.status == "pending":
            raise AppError("state_conflict", status_code=409)
        raise AppError("expense_not_found", status_code=404)

    db.expire_all()
    expense = get_expense(db, expense_id, tenant_id)
    if cleanup_duplicate_references:
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
    if commit:
        db.commit()
        db.refresh(expense)
    else:
        db.flush()
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

    Restore values: confirmed rows return to ``confirmed``; all others return
    to ``pending``. ``rejected_at`` is cleared, ``updated_at`` moves forward,
    and audit action ``undo`` is appended.

    **Child-resource /undo contract (ADR-0040)**: undo ONLY flips the parent
    Expense row. Splits, items, suggestion decisions, bill_split invitations
    and item-level acknowledge-mismatch are not rolled back; restoring the
    child subtree would be new ADR-covered behavior.

    **ABA (resolved, ADR-0041)**: the CAS token here is the monotonic
    ``row_version`` int (``WHERE row_version = expected``), which strictly
    increments per guarded UPDATE. This closes the old ``updated_at`` ABA
    window — two operations within ~15ms could write equal ``updated_at``
    values and defeat the OCC check; an integer that only ever goes up can't.
    """
    resolve_write_capability(db)
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
            status=case(
                (Expense.confirmed_at.is_not(None), "confirmed"),
                else_="pending",
            ),
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
