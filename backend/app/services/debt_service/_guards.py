"""ADR-0049 §5.2 adverse-interest admission guard for slice-2 direct writes.

Member Debt has adverse interests (§5). Writes that increase a member's burden,
reduce a creditor's receivable, or void a bill-split-sourced obligation require
the affected party's confirmation (§5.2 / §3.5) — those flows are the slice-3
``MemberRepaymentProposal`` / member-adjustment proposal domain, NOT a direct
fact write.

Slice 2 therefore opens *direct* committed fact writes (repayment / adjustment /
repayment-void / debt-void) only for ``counterparty_type='external'`` and
``source_type='manual'`` Debt — owner-side bookkeeping of external obligations
(credit card / loan / IOU). Member Debt, including manual rows seeded by a future
confirmation flow, stays behind the slice-3/4 affected-party workflow rather
than silently bypassing §5.2.

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

    Member Debt and bill-split-sourced Debt correction/repayment must go through
    the slice-3 affected-party confirmation flow, not a unilateral direct write.
    Rejected as ``state_conflict`` (409) — the obligation exists but cannot be
    mutated this way yet.
    """
    if debt.counterparty_type != "external" or debt.source_type != "manual":
        raise AppError("state_conflict", status_code=409)


def proposal_debtor_creditor(debt: Debt) -> tuple[int | None, int | None]:
    """Resolve (debtor_account_id, creditor_account_id) from the Debt direction.

    ``direction='i_owe'`` → the ledger owner owes the counterparty, so the owner
    is the debtor and the counterparty is the creditor. ``direction='owed_to_me'``
    is the mirror. Either side may be ``None`` for a non-member counterparty —
    :func:`guard_member_debt` is what restricts this flow to member Debt, so the
    proposal services only call this after that guard passes.
    """
    if debt.direction == "i_owe":
        return debt.owner_account_id, debt.counterparty_account_id
    return debt.counterparty_account_id, debt.owner_account_id


def guard_member_debt(debt: Debt) -> None:
    """The repayment-proposal flow (§3.2) is member-Debt only.

    A proposal models the debtor↔creditor adverse-interest handshake between two
    ledger accounts; an external (label-only) Debt has no member counterparty to
    confirm, so it stays on slice 2's direct owner-side bookkeeping.
    """
    if debt.counterparty_type != "member":
        raise AppError("repayment_proposal_requires_member_debt", status_code=409)


def guard_actor_is_debtor(debt: Debt, actor_account_id: int) -> None:
    """Only the debtor may propose or withdraw a repayment proposal (§3.2 / §5.2)."""
    debtor_account_id, _ = proposal_debtor_creditor(debt)
    if actor_account_id != debtor_account_id:
        raise AppError("repayment_proposal_debtor_only", status_code=403)


def guard_actor_is_creditor(debt: Debt, actor_account_id: int) -> None:
    """Only the creditor may confirm or reject a repayment proposal (§3.2 / §5.2)."""
    _, creditor_account_id = proposal_debtor_creditor(debt)
    if actor_account_id != creditor_account_id:
        raise AppError("repayment_proposal_creditor_only", status_code=403)
