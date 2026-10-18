"""ADR-0049 §杠杆③ repayment-draft resolution writes: confirm + dismiss.

Split from :mod:`_repayment_draft` (capture/list/audit view) to keep both modules
inside the codebase-audit 500-LOC budget. The confirm path commits one
``Repayment`` via :func:`record_repayment` under the parent-Debt lock; the draft
is locked first so the capture is claimed exactly once (state_conflict on a
concurrent resolution, single transaction).
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Debt, Expense, RepaymentDraft
from app.schemas import ExpenseOffsetCreateRequest, RepaymentCreateRequest
from app.schemas._accounting_time import AccountingTimeInput, AccountingTimeSnapshot
from app.services.currency_binding_service import resolve_write_capability
from app.services.currency_common import minor_amount_value
from app.services.debt_service._repayment import record_repayment
from app.services.time_service import now_utc


def _lock_pending_draft(db: Session, *, tenant_id: str, actor_account_id: int, public_id: str) -> RepaymentDraft:
    """``SELECT ... FOR UPDATE`` an account-scoped draft (the serialization point so two
    confirm/dismiss resolutions can't both fire). Account-scoped (§8 / privacy): only the
    capturing member may resolve their own draft; another member gets an existence-hidden 404."""
    draft = db.scalar(
        ledger_scoped_select(RepaymentDraft, tenant_id)
        .where(RepaymentDraft.created_by_account_id == actor_account_id)
        .where(RepaymentDraft.public_id == public_id)
        .with_for_update()
        .limit(1)
    )
    if draft is None:
        raise AppError("repayment_draft_not_found", status_code=404)
    return draft


def _reverse_source_expense(db: Session, draft: RepaymentDraft, actor_account_id: int) -> None:
    """Keep the original fact and cancel its spending effect, atomically with repayment."""
    if draft.source_expense_public_id is None:
        return
    # Expense offsets also project bill-split debt changes; import at command time
    # rather than creating an eager package initialization cycle.
    from app.services.expense_offset_service import create_expense_offset

    source = db.scalar(ledger_scoped_select(Expense, draft.tenant_id)
        .where(Expense.public_id == draft.source_expense_public_id).with_for_update())
    if (source is None or draft.source_expense_row_version is None
        or source.row_version != draft.source_expense_row_version):
        raise AppError("state_conflict", "原流水已变化，请回到原流水重新核对后作为还款处理。", status_code=409)
    if source.accounting_date is None:
        raise AppError("accounting_time_invalid", "请先补齐原流水的账务日期，再作为还款处理。", status_code=409)
    create_expense_offset(db, tenant_id=draft.tenant_id, expense_id=source.id,
        payload=ExpenseOffsetCreateRequest(kind="reversal", accounting_date=source.accounting_date,
            reason="误记为消费，已确认为还款", expected_row_version=draft.source_expense_row_version),
        effective_expected_row_version=draft.source_expense_row_version, actor_account_id=actor_account_id,
        actor_device_public_id=None, actor_device_name=None,
        idempotency_key=f"repayment-source:{draft.public_id}", commit=False)


def confirm_repayment_draft(
    db: Session,
    *,
    tenant_id: str,
    actor_account_id: int,
    public_id: str,
    target_debt_public_id: str,
    expected_row_version: int,
    idempotency_key: str,
    original_currency: str | None = None,
    original_amount: Decimal | None = None,
    time_input: AccountingTimeInput | None = None,
    commit: bool = False,
) -> RepaymentDraft:
    """Confirm a pending draft → record one ``Repayment`` on the chosen Debt (§杠杆③).

    The draft is locked first (status guard) so it claims the capture before any
    repayment is written: if a concurrent confirm already latched it, this raises
    ``state_conflict`` BEFORE :func:`record_repayment` runs, so the captured repayment
    is recorded exactly once. ``record_repayment`` enforces the external/manual guard,
    the §2.1 over-remaining check under the parent-Debt lock, and the OCC stale-intent
    fence on ``expected_row_version`` — a failure there rolls back the draft latch too
    (single transaction, ``commit=False``).
    """
    draft = _lock_pending_draft(db, tenant_id=tenant_id, actor_account_id=actor_account_id, public_id=public_id)
    if draft.status != "pending":
        # Already confirmed or dismissed — a second confirm cannot record again.
        raise AppError("state_conflict", status_code=409)

    # R13-8b：草稿与 parent debt 冻结币种不等即跨绑定错额 → drift 拒（挂账 D9）。
    target_home = db.scalar(
        ledger_scoped_select(Debt, tenant_id)
        .where(Debt.public_id == target_debt_public_id)
        .with_only_columns(Debt.home_currency_code)
    )
    if target_home is not None and target_home != draft.home_currency_code:
        raise AppError("currency_binding_drift", status_code=409)

    # Lock order follows the existing source correction path (Expense before Debt).
    # A rejected repayment rolls this reversal and its idempotency claim back too.
    _reverse_source_expense(db, draft, actor_account_id)

    if original_currency is not None or original_amount is not None:
        money = {"original_currency": original_currency, "original_amount": original_amount}
    elif draft.amount_cents is not None:
        # Existing home captures (including Expense bridges) keep their known amount.
        money = {"amount_cents": draft.amount_cents}
    else:
        money = {"original_currency": draft.original_currency_code,
            "original_amount": Decimal(minor_amount_value(draft.original_amount_minor, draft.original_currency_code))}
    result = record_repayment(
        db,
        tenant_id=tenant_id,
        public_id=target_debt_public_id,
        actor_account_id=actor_account_id,
        payload=RepaymentCreateRequest(
            **money,
            # Human review may correct the payment day without changing capture evidence.
            # Old submissions still use the original captured instant/snapshot, never now().
            paid_at=draft.captured_at if time_input is None else None,
            time_input=time_input,
            expected_row_version=expected_row_version,
        ),
        idempotency_key=idempotency_key,
        commit=False,
        captured_time=(AccountingTimeSnapshot.model_validate(draft.accounting_time_snapshot)
            if time_input is None and draft.accounting_time_snapshot is not None else None),
    )

    draft.status = "confirmed"
    draft.committed_debt_public_id = target_debt_public_id
    draft.committed_repayment_public_id = result.repayment_public_id
    draft.resolved_at = now_utc()
    draft.resolved_by_account_id = actor_account_id
    if draft.source_expense_public_id:
        from app.models import PaymentCapture
        from app.services.payment_capture_identity import append_decision, capture_query

        capture = db.scalar(capture_query(tenant_id, actor_account_id)
            .where(PaymentCapture.expense_public_id == draft.source_expense_public_id).with_for_update())
        if capture is not None:
            capture.repayment_public_id = draft.public_id
            append_decision(capture, kind="repayment", reason="误记为消费，人工确认还款并冲正原消费", actor_account_id=actor_account_id)
    db.flush()
    if commit:
        db.commit()
        db.refresh(draft)
    return draft


def dismiss_repayment_draft(
    db: Session,
    *,
    tenant_id: str,
    actor_account_id: int,
    public_id: str,
    commit: bool = False,
) -> RepaymentDraft:
    """Latch a pending draft ``dismissed`` (idempotent if already dismissed)."""
    draft = _lock_pending_draft(db, tenant_id=tenant_id, actor_account_id=actor_account_id, public_id=public_id)
    if draft.status == "dismissed":
        return draft  # idempotent: already dismissed
    if draft.status == "confirmed":
        raise AppError("state_conflict", status_code=409)

    resolve_write_capability(db)
    draft.status = "dismissed"
    draft.resolved_at = now_utc()
    draft.resolved_by_account_id = actor_account_id
    db.flush()
    if commit:
        db.commit()
        db.refresh(draft)
    return draft
