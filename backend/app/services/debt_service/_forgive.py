"""ADR-0049 §3.7 / §4 creditor forgiveness: waive a member Debt's remaining.

"算了，不用还了" is the Communal escape valve (§7.0): the creditor relinquishes
their OWN remaining claim so the debtor no longer owes it. Because it benefits the
debtor only (no adverse interest), it is a UNILATERAL creditor op — no debtor
confirmation, unlike a member void / principal-raising adjustment (§3.3 / §3.5 /
§5.2). It is member-Debt only.

Fold semantics (§3.7): forgiveness is an append-only ``DebtForgiveness`` fact whose
amount is the ``remaining_before`` snapshotted under the §2.1 parent-row lock, so a
concurrent repayment and forgiveness cannot both read the same pre-state and drive
``remaining < 0``. ``compute_remaining`` subtracts it, so the Debt folds to
``cleared`` (a completion that counts toward §6 "two-clear"), NOT ``voided`` —
``derive_status`` only latches ``voided`` for an explicit ``DebtVoid``.

§5.2: the creditor may be a member of ANOTHER ledger (a bill_split Debt is owned by
the receiver's ledger), so the Debt is resolved and locked by participant identity,
not by ``tenant_id`` ledger scope — mirroring :func:`confirm_repayment_proposal`. The
member + creditor guards run before the lock; ``lock_and_fold(account_id=...)``
re-admits the same participant under the row lock.
"""

from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Debt, DebtForgiveness, MemberRepaymentProposal
from app.services.debt_service._guards import (
    guard_actor_is_creditor,
    guard_member_debt,
)
from app.services.debt_service._query import resolve_debt_for_participant
from app.services.debt_service._serialize import lock_and_fold
from app.services.time_service import now_utc


def _supersede_pending_on_forgive(
    db: Session, *, debt_id: int, actor_account_id: int
) -> None:
    """Guarded flip: any pending proposal on this Debt → ``superseded`` (§4 F5).

    Forgiving the remaining makes the debtor's in-flight "I paid" proposal moot —
    leaving it ``pending`` would let the creditor later "confirm" a repayment on an
    already-cleared Debt. ``WHERE status='pending'`` makes this idempotent: rowcount 0
    (no pending) or 1 (one superseded) are both fine, and the parent-Debt row lock held
    by :func:`lock_and_fold` serialises this against a racing confirm/withdraw. NOT the
    create-scoped ``_resolve_superseded_pending`` (which requires the client to name the
    proposal it saw) — forgiveness sweeps whatever pending proposal exists.
    """
    db.execute(
        update(MemberRepaymentProposal)
        .where(MemberRepaymentProposal.debt_id == debt_id)
        .where(MemberRepaymentProposal.status == "pending")
        .values(
            status="superseded",
            resolved_at=now_utc(),
            resolved_by_account_id=actor_account_id,
        )
    )


def forgive_debt(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    actor_account_id: int,
    expected_row_version: int | None,
    idempotency_key: str,
    commit: bool = False,
) -> Debt:
    """Creditor waives a member Debt's remaining — folds it to ``cleared`` (§3.7 / §4).

    Member-Debt only (external Debt has its own §3.5 direct void) and creditor only
    (the only party who can give up their own claim). The §2.1 parent-Debt
    serialization (FOR UPDATE + bump) runs inside :func:`lock_and_fold`; the
    ``remaining_before`` snapshotted there is the forgiven amount. A Debt that already
    folds to 0 (fully repaid or previously forgiven) is rejected as ``state_conflict``
    rather than recording a zero-amount fact that would pollute history and could falsely
    trip the §5 celebration. ``commit=False`` lets the route commit the fact + parent bump
    + [[0042]] idempotency-success record in one transaction.
    """
    debt, _ = resolve_debt_for_participant(
        db, public_id=public_id, ledger_id=tenant_id, account_id=actor_account_id
    )
    guard_member_debt(debt)
    guard_actor_is_creditor(debt, actor_account_id)

    def _mutate(locked_debt: Debt, remaining_before: int) -> None:
        # §4 F2: nothing left to forgive (already two-clear / already forgiven). Reject
        # rather than insert a 0-amount fact (CHECK amount_cents > 0 would also reject it,
        # but the explicit 409 is the user-facing contract).
        if remaining_before == 0:
            raise AppError("state_conflict", status_code=409)
        db.add(
            DebtForgiveness(
                debt_id=locked_debt.id,
                amount_cents=remaining_before,
                actor_account_id=actor_account_id,
                idempotency_key=idempotency_key,
            )
        )
        db.flush()
        # §4 F5: a debtor's pending "I paid" proposal is moot once forgiven — sweep it.
        _supersede_pending_on_forgive(
            db, debt_id=locked_debt.id, actor_account_id=actor_account_id
        )

    debt, _ = lock_and_fold(
        db,
        tenant_id=tenant_id,
        public_id=public_id,
        expected_row_version=expected_row_version,
        mutate=_mutate,
        account_id=actor_account_id,  # §5.2 cross-ledger creditor admission
    )
    # Mirror slice-2 ``void_debt``'s commit boundary: only the commit=True direct caller
    # commits + refreshes here. With commit=False the ROUTE owns the post-commit
    # expire_all + participant re-serialise (it commits the [[0042]] success record in the
    # same transaction first), so this service must NOT expire/commit early.
    if commit:
        db.commit()
        db.refresh(debt)
    return debt


__all__ = ["forgive_debt"]
