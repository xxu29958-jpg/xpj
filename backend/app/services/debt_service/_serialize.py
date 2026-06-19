"""ADR-0049 §2.1 parent-Debt serialization — the single fold-changing entry.

Every fold-changing write (repayment / adjustment / repayment-void / debt-void)
inserts an append-only child fact AND must serialize against concurrent writers
on the SAME parent Debt so an overpayment check reads authoritative facts (§2.1 /
F8). This module is the one place that takes the parent row lock, so the four
write services cannot drift into four hand-rolled ``FOR UPDATE`` blocks.

Why ``SELECT ... FOR UPDATE`` and not a bare ``row_version`` CAS bump: this path
is read-check-insert, not a token-gated single-row UPDATE. The overpay check
must see the OTHER writer's just-committed child fact before inserting its own;
a pure CAS bump on the parent lets two distinct repayments both succeed
(``row_version`` 1→2, 2→3) while both child facts land — a double-spend. The row
lock physically serializes "read facts → check → insert child → bump parent": the
second writer blocks until the first COMMITs, then recomputes ``remaining`` from
facts that now include the first insert. This mirrors slice 1's bill-split
``create_invitation`` (FOR-UPDATE the parent expense, then read the active-split
total + cap check + insert) — the same weapon the cloud-hardening audit gate
pins, not a second one.

``expected_row_version`` is narrowed to intent fencing + the [[0042]] fingerprint
(§3.6): held under the lock, a mismatch means the user's submitted intent was
based on stale Debt state, so we reject with ``state_conflict`` (409) BEFORE the
overpay check. Serial correctness is the row lock's job, not the token's — F8
holds even when both writers omit ``expected_row_version`` because the overpay
check runs from authoritative facts inside the locked section.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Debt
from app.services.debt_service._fold import compute_remaining, derive_status
from app.services.debt_service._query import participant_can_access
from app.services.optimistic_concurrency import bump_row_version
from app.services.time_service import now_utc

T = TypeVar("T")


def _lock_debt(
    db: Session, *, tenant_id: str, public_id: str, account_id: int | None
) -> Debt:
    """``SELECT Debt ... FOR UPDATE`` with the right §2.1/§5.2 scope.

    ``account_id is None`` (slice-2 external/manual fact writes) keeps the
    ledger-scoped lock: a Debt in another ledger is invisible (``debt_not_found``).
    ``account_id`` supplied (slice-5 member proposal confirm) locks by public id,
    then admits the actor when they are a ledger member OR the cross-ledger member
    counterparty (§5.2 creditor) — anyone else still gets ``debt_not_found`` with
    the same existence hiding. The row lock is held either way.
    """
    if account_id is None:
        debt = db.scalar(
            ledger_scoped_select(Debt, tenant_id)
            .where(Debt.public_id == public_id)
            .with_for_update()
            .limit(1)
        )
        if debt is None:
            raise AppError("debt_not_found", status_code=404)
        return debt
    debt = db.scalar(
        select(Debt).where(Debt.public_id == public_id).with_for_update().limit(1)
    )
    if debt is None:
        raise AppError("debt_not_found", status_code=404)
    is_ledger_member, is_counterparty = participant_can_access(
        debt, ledger_id=tenant_id, account_id=account_id
    )
    if not (is_ledger_member or is_counterparty):
        raise AppError("debt_not_found", status_code=404)
    return debt


def lock_and_fold(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    expected_row_version: int | None,
    mutate: Callable[[Debt, int], T],
    account_id: int | None = None,
) -> tuple[Debt, T]:
    """Serialize one fold-changing write on the parent Debt row (§2.1).

    1. ``SELECT Debt ... FOR UPDATE`` (ledger-scoped, or — when ``account_id`` is
       given — participant-scoped per §5.2; missing/forbidden → ``debt_not_found``
       404 with cross-ledger existence hiding).
    2. A voided Debt is terminal — no further facts (``debt_already_voided``).
    3. Stale-intent fence: if ``expected_row_version`` is supplied and the locked
       Debt's ``row_version`` differs, the user acted on stale state →
       ``state_conflict`` (409).
    4. ``remaining_before`` = authoritative fold under the lock.
    5. ``mutate(debt, remaining_before)`` runs the per-write business check and
       inserts its child fact (it owns ``debt_overpay_rejected`` /
       ``debt_adjustment_negative_remaining`` / ``repayment_not_found`` etc.) and
       returns whatever the caller needs back.
    6. ``remaining_after`` = fold including the just-inserted fact.
    7. Bump the parent ``row_version`` (concurrency token, NOT financial truth),
       touch ``updated_at``, and re-derive ``status`` (open↔cleared latch; a
       DebtVoid mutate set ``status='voided'`` itself and ``derive_status``
       latches it).

    ``account_id`` is the §5.2 participant admission: ``None`` (slice-2 facts)
    keeps the pure ledger-scoped lock; supplied (slice-5 member repayment confirm)
    admits a cross-ledger participant. Serial correctness (F8) is unaffected — the
    row lock physically serializes every fold-changing writer on this Debt
    regardless of which scope admitted them.

    Returns the locked Debt plus the ``mutate`` result. The route commits the
    child fact + parent bump + [[0042]] idempotency-success record in one
    transaction.
    """
    debt = _lock_debt(db, tenant_id=tenant_id, public_id=public_id, account_id=account_id)
    if debt.status == "voided":
        raise AppError("debt_already_voided", status_code=409)
    if expected_row_version is not None and debt.row_version != expected_row_version:
        raise AppError("state_conflict", status_code=409)

    remaining_before = compute_remaining(db, debt)
    result = mutate(debt, remaining_before)
    db.flush()

    remaining_after = compute_remaining(db, debt)
    bump_row_version(debt)
    debt.updated_at = now_utc()
    debt.status = derive_status(debt, remaining_after)
    return debt, result


def lock_debt_for_intent(
    db: Session, *, tenant_id: str, public_id: str, account_id: int | None = None
) -> Debt:
    """FOR UPDATE the parent Debt for a NON-fold-changing write that still must read
    the authoritative fold under the lock (ADR-0049 §3.2 proposal create: refuse a
    pending proposal on a Debt a concurrent confirm/forgive has already settled).

    Unlike :func:`lock_and_fold` this takes the parent row lock but NEVER bumps
    ``row_version``, touches ``updated_at``, or re-derives ``status`` — a pending
    proposal is an INTENT, not a §2 fact, so it must not move the fold or the
    concurrency token. It also leaves the voided/stale-intent gating to the caller
    (a proposal create reports voided as ``debt_already_voided`` itself). Keeping
    the ``FOR UPDATE`` here (not a hand-rolled lock in ``_proposal``) preserves the
    module invariant that this file is the single place that locks a parent Debt.

    Same §2.1/§5.2 participant scoping as :func:`lock_and_fold`: ``account_id is
    None`` keeps the ledger-scoped lock; supplied admits the cross-ledger member
    counterparty, with the same ``debt_not_found`` existence hiding for everyone
    else.
    """
    return _lock_debt(db, tenant_id=tenant_id, public_id=public_id, account_id=account_id)
