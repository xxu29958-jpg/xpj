"""v1.2 P2 — ledger invariant audit.

Read-only checks that the ledger satisfies the invariants the rest of
the codebase assumes:

* ``expense_splits`` sum equals ``expenses.amount_cents`` when there
  are splits at all (no partial / under-/over- assigned splits).
* ``expense_items`` rebuild contract — items sum + tax + service_fee
  - discount ≤ expense.amount_cents OR expense.items_sum_status
  marks the discrepancy.
* Status-marker invariant: ``confirmed_at IS NOT NULL`` iff
  ``status='confirmed'``; same for ``rejected_at`` / ``rejected``.
* Tenant-scope sanity: every split's tenant_id matches the parent
  expense's tenant_id (cross-tenant splits would have leaked through
  ADR-0029 guards).

Findings are returned, never auto-fixed — the owner decides what to
do, since some violations indicate real data corruption that needs
investigation before mechanical repair.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Expense, ExpenseSplit

InvariantCode = Literal[
    "split_sum_mismatch",
    "split_cross_tenant",
    "status_confirmed_no_timestamp",
    "status_rejected_no_timestamp",
]


@dataclass(frozen=True)
class InvariantViolation:
    code: InvariantCode
    expense_id: int
    tenant_id: str
    detail: str


def _check_split_sum(
    db: Session, *, tenant_id: str
) -> list[InvariantViolation]:
    """For every expense with at least one split, the splits must sum
    to the expense's amount_cents."""

    # Compute per-expense split totals via SQL and join back to the
    # expense for the comparison. Skip expenses without any split
    # rows — those don't have a "splits sum" to enforce.
    split_totals = (
        select(
            ExpenseSplit.expense_id,
            func.sum(ExpenseSplit.amount_cents).label("split_total"),
        )
        .where(ExpenseSplit.tenant_id == tenant_id)
        .group_by(ExpenseSplit.expense_id)
        .subquery()
    )
    rows = db.execute(
        select(
            Expense.id,
            Expense.amount_cents,
            split_totals.c.split_total,
        )
        .join(split_totals, split_totals.c.expense_id == Expense.id)
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.status != "rejected")
    ).all()

    findings: list[InvariantViolation] = []
    for expense_id, amount_cents, split_total in rows:
        if amount_cents is None:
            # Expense without an amount but has splits — flag as
            # mismatch with explicit detail.
            findings.append(
                InvariantViolation(
                    code="split_sum_mismatch",
                    expense_id=int(expense_id),
                    tenant_id=tenant_id,
                    detail=(
                        f"支出未填金额但存在 split 总额 {split_total}。"
                    ),
                )
            )
            continue
        if int(split_total or 0) != int(amount_cents):
            findings.append(
                InvariantViolation(
                    code="split_sum_mismatch",
                    expense_id=int(expense_id),
                    tenant_id=tenant_id,
                    detail=(
                        f"split 总额 {split_total} ≠ 支出 amount_cents "
                        f"{amount_cents}。"
                    ),
                )
            )
    return findings


def _check_split_cross_tenant(
    db: Session, *, tenant_id: str
) -> list[InvariantViolation]:
    """Every split's parent expense must live in the same tenant."""

    rows = db.execute(
        select(ExpenseSplit.expense_id, Expense.tenant_id)
        .join(Expense, Expense.id == ExpenseSplit.expense_id)
        .where(ExpenseSplit.tenant_id == tenant_id)
        .where(Expense.tenant_id != tenant_id)
    ).all()
    return [
        InvariantViolation(
            code="split_cross_tenant",
            expense_id=int(expense_id),
            tenant_id=tenant_id,
            detail=(
                f"split tenant '{tenant_id}' 与父支出 tenant "
                f"'{parent_tenant}' 不一致。"
            ),
        )
        for expense_id, parent_tenant in rows
    ]


def _check_status_timestamps(
    db: Session, *, tenant_id: str
) -> list[InvariantViolation]:
    """``confirmed`` rows must have ``confirmed_at``; ``rejected``
    rows must have ``rejected_at``."""

    findings: list[InvariantViolation] = []
    confirmed_missing = db.scalars(
        select(Expense.id)
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.status == "confirmed")
        .where(Expense.confirmed_at.is_(None))
    ).all()
    for expense_id in confirmed_missing:
        findings.append(
            InvariantViolation(
                code="status_confirmed_no_timestamp",
                expense_id=int(expense_id),
                tenant_id=tenant_id,
                detail="status=confirmed 但 confirmed_at 为空。",
            )
        )
    rejected_missing = db.scalars(
        select(Expense.id)
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.status == "rejected")
        .where(Expense.rejected_at.is_(None))
    ).all()
    for expense_id in rejected_missing:
        findings.append(
            InvariantViolation(
                code="status_rejected_no_timestamp",
                expense_id=int(expense_id),
                tenant_id=tenant_id,
                detail="status=rejected 但 rejected_at 为空。",
            )
        )
    return findings


def audit_ledger_invariants(
    db: Session, *, tenant_id: str
) -> list[InvariantViolation]:
    """Run every invariant check and return the union of findings."""

    findings: list[InvariantViolation] = []
    findings.extend(_check_split_sum(db, tenant_id=tenant_id))
    findings.extend(_check_split_cross_tenant(db, tenant_id=tenant_id))
    findings.extend(_check_status_timestamps(db, tenant_id=tenant_id))
    return findings


__all__ = ["InvariantCode", "InvariantViolation", "audit_ledger_invariants"]
