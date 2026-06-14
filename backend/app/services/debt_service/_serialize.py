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

from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Debt
from app.services.debt_service._fold import compute_remaining, derive_status
from app.services.optimistic_concurrency import bump_row_version
from app.services.time_service import now_utc

T = TypeVar("T")


def lock_and_fold(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    expected_row_version: int | None,
    mutate: Callable[[Debt, int], T],
) -> tuple[Debt, T]:
    """Serialize one fold-changing write on the parent Debt row (§2.1).

    1. ``SELECT Debt ... FOR UPDATE`` (ledger-scoped; missing → ``debt_not_found``
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

    Returns the locked Debt plus the ``mutate`` result. The route commits the
    child fact + parent bump + [[0042]] idempotency-success record in one
    transaction.
    """
    debt = db.scalar(
        ledger_scoped_select(Debt, tenant_id)
        .where(Debt.public_id == public_id)
        .with_for_update()
        .limit(1)
    )
    if debt is None:
        raise AppError("debt_not_found", status_code=404)
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
