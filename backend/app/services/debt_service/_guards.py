"""ADR-0049 §5.2 adverse-interest admission guard for slice-2 direct writes.

Member Debt has adverse interests (§5). Writes that increase a member's burden,
reduce a creditor's receivable, or void a bill-split-sourced obligation require
the affected party's confirmation (§5.2 / §3.5) — those flows are the slice-3
``MemberRepaymentProposal`` / member-adjustment proposal domain, NOT a direct
fact write.

Slice 2 therefore opens *direct* committed fact writes (repayment / adjustment /
repayment-void / debt-void) only for ``source_type='manual'`` Debt — owner-side
bookkeeping of external obligations (credit card / loan / IOU) and manually
recorded member figures the owner controls. A ``source_type='bill_split'`` Debt
carries the debtor's accepted-invitation adverse interest, so any direct fact
write against it is refused here and deferred to the slice-3/4 confirmation flow
rather than silently bypassing §5.2.

Slice 3 follow-up: when ``MemberRepaymentProposal`` (and, if exposed, the member
adjustment proposal mirroring §3.2's fields / lifecycle / one-pending invariant
per §10) lands, route member-Debt debtor "I paid" and burden-increasing
adjustments through the proposal + affected-party confirmation instead of
widening this guard.
"""

from __future__ import annotations

from app.errors import AppError
from app.models import Debt


def guard_direct_fact_writable(debt: Debt) -> None:
    """Refuse a direct committed fact write on an adverse-interest Debt (§5.2).

    A bill-split-sourced Debt's correction/repayment must go through the slice-3
    affected-party confirmation flow, not a unilateral direct write. Rejected as
    ``state_conflict`` (409) — the obligation exists but cannot be mutated this
    way yet.
    """
    if debt.source_type != "manual":
        raise AppError("state_conflict", status_code=409)
