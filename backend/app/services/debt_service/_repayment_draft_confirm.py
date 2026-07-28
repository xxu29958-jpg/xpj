"""ADR-0049 §杠杆③ repayment-draft resolution writes: confirm + dismiss.

Split from :mod:`_repayment_draft` (capture/list/audit view) to keep both modules
inside the codebase-audit 500-LOC budget. The confirm path commits one
``Repayment`` via :func:`record_repayment` under the parent-Debt lock; the draft
is locked first so the capture is claimed exactly once (state_conflict on a
concurrent resolution, single transaction).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Debt, RepaymentDraft
from app.schemas import RepaymentCreateRequest
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


def confirm_repayment_draft(
    db: Session,
    *,
    tenant_id: str,
    actor_account_id: int,
    public_id: str,
    target_debt_public_id: str,
    expected_row_version: int,
    idempotency_key: str,
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
        ledger_scoped_select(Debt, tenant_id).where(Debt.public_id == target_debt_public_id).with_only_columns(Debt.home_currency_code)
    )
    if target_home is not None and target_home != draft.home_currency_code:
        raise AppError("currency_binding_drift", status_code=409)

    result = record_repayment(
        db,
        tenant_id=tenant_id,
        public_id=target_debt_public_id,
        actor_account_id=actor_account_id,
        payload=RepaymentCreateRequest(
            amount_cents=draft.amount_cents,
            # The whole point of NLS capture is that it knows WHEN the repayment happened
            # (captured_at = the notification post time). Confirm may be days later, so pass
            # captured_at through as the repayment's paid_at instead of letting
            # record_repayment fall back to now() — otherwise a delayed review back-stamps
            # the debt history to review time. (The §6 projection keys off created_at, not
            # paid_at, so this only sharpens the user-facing payment time, never the velocity.)
            paid_at=draft.captured_at,
            expected_row_version=expected_row_version,
        ),
        idempotency_key=idempotency_key,
        commit=False,
    )

    draft.status = "confirmed"
    draft.committed_debt_public_id = target_debt_public_id
    draft.committed_repayment_public_id = result.repayment_public_id
    draft.resolved_at = now_utc()
    draft.resolved_by_account_id = actor_account_id
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

    draft.status = "dismissed"
    draft.resolved_at = now_utc()
    draft.resolved_by_account_id = actor_account_id
    db.flush()
    if commit:
        db.commit()
        db.refresh(draft)
    return draft
