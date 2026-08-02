"""ADR-0049 §2 derived fold: remaining / paid / status from append-only facts.

Pure read-only. ``remaining`` and ``paid`` are NEVER stored as truth (§2 / §10);
they are recomputed from the parent ``Debt`` principal plus the append-only
``Repayment`` / ``DebtAdjustment`` / ``RepaymentVoid`` / ``DebtForgiveness`` facts
every time. Slice 1 never writes any fact row, so for a freshly created Debt these
collapse to ``remaining == principal`` and ``paid == 0``. Slice 8e-3 adds the
``DebtForgiveness`` subtraction (§3.7 / §4): a creditor waiver drives ``remaining``
to 0 → ``cleared`` (a completion), distinct from a ``DebtVoid`` → ``voided`` latch.

The fold-CHANGING write paths (committing a repayment / adjustment / void) and
the §2.1 parent-row serialization they require land in slice 2. This module is
the single definition both that future writer and the read endpoints share.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Debt, DebtAdjustment, DebtForgiveness, Repayment, RepaymentVoid
from app.money_contract import fold_sum_to_int, projection_sum_to_int
from app.services.time_service import ensure_utc


def _materialize_total(value: object, *, label: str, for_write: bool) -> int:
    if for_write:
        return fold_sum_to_int(value, label=label)
    return projection_sum_to_int(value, label=label)


def _non_voided_repayment_total(
    db: Session, debt_id: int, *, for_write: bool = False
) -> int:
    """Sum of repayments on the Debt that have NOT been voided (§3.4).

    A voided repayment keeps its original row (never deleted) but is excluded
    from the fold via a NOT EXISTS against ``RepaymentVoid``.
    """
    voided = select(RepaymentVoid.repayment_id).where(
        RepaymentVoid.repayment_id == Repayment.id
    )
    total = db.scalar(
        select(func.coalesce(func.sum(Repayment.amount_cents), 0))
        .where(Repayment.debt_id == debt_id)
        .where(~voided.exists())
    )
    return _materialize_total(
        total,
        label="debt.repayment_total",
        for_write=for_write,
    )


def _adjustment_total(
    db: Session, debt_id: int, *, for_write: bool = False
) -> int:
    """Signed sum of all append-only adjustments on the Debt (§3.3)."""
    total = db.scalar(
        select(func.coalesce(func.sum(DebtAdjustment.amount_cents), 0)).where(
            DebtAdjustment.debt_id == debt_id
        )
    )
    return _materialize_total(
        total,
        label="debt.adjustment_total",
        for_write=for_write,
    )


def _forgiveness_total(
    db: Session, debt_id: int, *, for_write: bool = False
) -> int:
    """Sum of creditor forgiveness facts on the Debt (§3.7 / §4, slice 8e-3).

    A ``DebtForgiveness`` waives the creditor's remaining claim; its amount is the
    ``remaining_before`` snapshotted under the §2.1 lock, so the fold subtracts it to
    drive the Debt to ``cleared`` (a completion, not a void).
    """
    total = db.scalar(
        select(func.coalesce(func.sum(DebtForgiveness.amount_cents), 0)).where(
            DebtForgiveness.debt_id == debt_id
        )
    )
    return _materialize_total(
        total,
        label="debt.forgiveness_total",
        for_write=for_write,
    )


def has_forgiveness(db: Session, debt_id: int) -> bool:
    """Whether any ``DebtForgiveness`` fact exists for this Debt (drives ``is_forgiven``).

    A forgiven Debt folds to ``cleared`` via :func:`compute_remaining`; the response
    distinguishes it from a repayment-cleared Debt by also checking this fact exists
    (§4.3 — the debtor sees a "被请客" headline, not a generic "两清").
    """
    return (
        db.scalar(
            select(DebtForgiveness.id).where(DebtForgiveness.debt_id == debt_id).limit(1)
        )
        is not None
    )


def latest_fact_at(db: Session, debt: Debt) -> datetime | None:
    """The most recent append-only fact ``created_at`` on the Debt, or ``None`` if it has none.

    Spans every fold-changing fact — ``Repayment`` / ``DebtAdjustment`` / ``DebtForgiveness`` /
    ``RepaymentVoid`` — i.e. every recorded action that moves the derived ``remaining`` over
    time. (A ``DebtVoid`` latch is excluded: a voided Debt is dropped from the projection set
    before this is reached.) Filters on ``created_at`` — the recording cadence, indexed by the
    ``ix_*_debt_created`` composites — never the user-editable ``paid_at``, mirroring
    :func:`compute_remaining_as_of`. The 8e-6d staleness floor (杠杆④) uses it to detect a
    payoff projection still being drawn from weeks-old data.
    """
    candidates = [
        db.scalar(select(func.max(Repayment.created_at)).where(Repayment.debt_id == debt.id)),
        db.scalar(
            select(func.max(DebtAdjustment.created_at)).where(DebtAdjustment.debt_id == debt.id)
        ),
        db.scalar(
            select(func.max(DebtForgiveness.created_at)).where(
                DebtForgiveness.debt_id == debt.id
            )
        ),
        db.scalar(
            select(func.max(RepaymentVoid.created_at)).where(
                RepaymentVoid.repayment_id.in_(
                    select(Repayment.id).where(Repayment.debt_id == debt.id)
                )
            )
        ),
    ]
    present = [ensure_utc(ts) for ts in candidates if ts is not None]
    return max(present) if present else None


def compute_paid(db: Session, debt: Debt) -> int:
    """Home-currency minor units repaid so far (non-voided repayments only).

    Forgiveness is NOT repayment: it does not count as ``paid`` (no money changed
    hands); it only reduces ``remaining`` (§3.7).
    """
    return _non_voided_repayment_total(db, debt.id)


def _compute_remaining(
    db: Session,
    debt: Debt,
    *,
    for_write: bool,
) -> int:
    materialize = fold_sum_to_int if for_write else projection_sum_to_int
    principal = materialize(
        debt.principal_amount_cents,
        label="debt.principal",
    )
    total = (
        principal
        + _adjustment_total(db, debt.id, for_write=for_write)
        - _non_voided_repayment_total(db, debt.id, for_write=for_write)
        - _forgiveness_total(db, debt.id, for_write=for_write)
    )
    return _materialize_total(
        total,
        label="debt.remaining",
        for_write=for_write,
    )


def compute_remaining(db: Session, debt: Debt) -> int:
    """Read projection of the canonical remaining balance."""

    return _compute_remaining(db, debt, for_write=False)


def compute_remaining_for_write(db: Session, debt: Debt) -> int:
    """Canonical remaining balance inside a serialized write transaction."""

    return _compute_remaining(db, debt, for_write=True)


def _non_voided_repayment_total_as_of(db: Session, debt_id: int, cutoff: datetime) -> int:
    """Non-voided repayments on the Debt that were committed AND not yet voided by ``cutoff``.

    Filters on ``created_at`` (the recording timestamp, indexed by
    ``ix_repayments_debt_created``) — NOT the user-editable ``paid_at``. A repayment
    counts at the cutoff only if it was created on/before the cutoff and no
    ``RepaymentVoid`` for it was created on/before the cutoff either (a later void
    correctly shows up as remaining going back UP over the window).
    """
    voided = select(RepaymentVoid.repayment_id).where(
        RepaymentVoid.repayment_id == Repayment.id,
        RepaymentVoid.created_at <= cutoff,
    )
    total = db.scalar(
        select(func.coalesce(func.sum(Repayment.amount_cents), 0))
        .where(Repayment.debt_id == debt_id)
        .where(Repayment.created_at <= cutoff)
        .where(~voided.exists())
    )
    return projection_sum_to_int(total, label="debt.repayment_total_as_of")


def _adjustment_total_as_of(db: Session, debt_id: int, cutoff: datetime) -> int:
    """Signed sum of adjustments recorded on/before ``cutoff`` (created_at filter)."""
    total = db.scalar(
        select(func.coalesce(func.sum(DebtAdjustment.amount_cents), 0))
        .where(DebtAdjustment.debt_id == debt_id)
        .where(DebtAdjustment.created_at <= cutoff)
    )
    return projection_sum_to_int(total, label="debt.adjustment_total_as_of")


def _forgiveness_total_as_of(db: Session, debt_id: int, cutoff: datetime) -> int:
    """Sum of forgiveness facts recorded on/before ``cutoff`` (created_at filter)."""
    total = db.scalar(
        select(func.coalesce(func.sum(DebtForgiveness.amount_cents), 0))
        .where(DebtForgiveness.debt_id == debt_id)
        .where(DebtForgiveness.created_at <= cutoff)
    )
    return projection_sum_to_int(total, label="debt.forgiveness_total_as_of")


def compute_remaining_as_of(db: Session, debt: Debt, cutoff: datetime) -> int:
    """The Debt's ``remaining`` folded from only the facts recorded on/before ``cutoff``.

    Mirrors :func:`compute_remaining` (principal + adjustments − non-voided repayments −
    forgiveness) but filters every fact on ``created_at <= cutoff``. The 8e-6b payoff
    projection uses it to measure the ACTUAL reduction in remaining over a window
    (``remaining_as_of(window_start) − remaining_now``): because it folds the same
    quantity the projection consumes, a Debt resolved by forgiveness or a negative
    ``DebtAdjustment`` (a write-off, with ZERO repayment rows) shows real downward
    velocity instead of looking stalled (ADR-0049 §7.0 R4 — never misjudge a debt that
    is being resolved). Returns 0 when the Debt did not yet exist at the cutoff
    (``created_at > cutoff``) so a Debt added mid-window counts as added remaining, not
    as observed paydown.
    """
    if ensure_utc(debt.created_at) > ensure_utc(cutoff):
        return 0
    principal = projection_sum_to_int(
        debt.principal_amount_cents,
        label="debt.principal_as_of",
    )
    total = (
        principal
        + _adjustment_total_as_of(db, debt.id, cutoff)
        - _non_voided_repayment_total_as_of(db, debt.id, cutoff)
        - _forgiveness_total_as_of(db, debt.id, cutoff)
    )
    return projection_sum_to_int(total, label="debt.remaining_as_of")


def derive_status(debt: Debt, remaining: int) -> str:
    """Derive the lifecycle status from the fold.

    A Debt voided via an append-only ``DebtVoid`` fact stays ``voided`` (that
    latch is driven by slice 2's void write); otherwise the status follows the
    fold — ``cleared`` when nothing remains, else ``open``. ``status=cleared`` is
    a latch reached by transition, not an independently editable balance (§2).
    """
    if debt.status == "voided":
        return "voided"
    return "cleared" if remaining == 0 else "open"
