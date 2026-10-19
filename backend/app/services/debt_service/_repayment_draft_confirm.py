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
from app.models import Debt, RepaymentDraft
from app.schemas import RepaymentCreateRequest
from app.schemas._accounting_time import AccountingTimeInput, AccountingTimeSnapshot
from app.services.currency_binding_service import resolve_write_capability
from app.services.currency_common import minor_amount_value
from app.services.debt_service._repayment import record_repayment
from app.services.repayment_draft_resolution import (
    lock_repayment_draft as _lock_pending_draft,
)
from app.services.repayment_draft_resolution import (
    resolve_repayment_draft,
)
from app.services.repayment_draft_resolution import (
    reverse_source_expense as _reverse_source_expense,
)
from app.services.time_service import now_utc


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

    resolve_repayment_draft(db, draft, actor_account_id=actor_account_id,
        debt_public_id=target_debt_public_id, repayment_public_id=result.repayment_public_id)
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
