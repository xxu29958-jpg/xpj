"""ADR-0049 Debt domain service (slice 1: create / list / get; slice 2: facts;
slice 3: member repayment proposals).

Public face mirrors ``goal_service``: the route layer imports these names and
never reaches into the ``_create`` / ``_query`` / ``_fold`` / ``_serialize`` /
``_money`` / ``_guards`` / ``_proposal`` submodules. The submodules exist only to
keep each file under the 500-line layering budget and to pin §2.1 in one place.

Slice 1 exposes external/manual Debt creation plus ledger-scoped list/get with
the derived ``remaining`` / ``paid`` fold. Slice 2 adds the fold-changing writes
— ``record_repayment`` / ``record_adjustment`` / ``void_repayment`` /
``void_debt`` — each serialized on the parent Debt row per §2.1. Slice 3 adds the
member ``MemberRepaymentProposal`` workflow — ``create_repayment_proposal`` /
``withdraw_repayment_proposal`` / ``confirm_repayment_proposal`` /
``reject_repayment_proposal`` / ``list_repayment_proposals`` (§3.2); only confirm
is fold-changing and goes through the same §2.1 serialization.

Slice 5 makes the proposal workflow ACCOUNT-scoped (§5.2): a member Debt's two
parties can live in different ledgers (a bill_split Debt is owned by the
receiver's ledger with the sender as the cross-ledger creditor), so the proposal
ops + the participant Debt read resolve by participant identity (debtor OR
creditor account) unioned with ledger membership, not by ledger scope alone.
``get_participant_debt_response`` redacts the counterparty's ledger id for a
participant-but-not-member view (the Debt shell only). This is the prerequisite
for enabling ``DEBT_ROLLOUT_ENABLED`` (ADR §0.1).

Slice 8e-3 adds ``forgive_debt`` (§3.7 / §4): a creditor unilaterally waives a member
Debt's remaining ("算了，不用还了"). It is fold-changing (a ``DebtForgiveness`` fact
drives ``remaining`` to 0 → ``cleared``, not ``voided``) so it shares the same §2.1
``lock_and_fold`` serialization + §5.2 participant scope as the proposal confirm, and
supersedes any pending proposal in the same transaction.
"""

from __future__ import annotations

from app.services.debt_service._adjustment import record_adjustment
from app.services.debt_service._create import create_bill_split_debt, create_debt
from app.services.debt_service._fold import (
    compute_paid,
    compute_remaining,
    compute_remaining_as_of,
    derive_status,
    latest_fact_at,
)
from app.services.debt_service._forgive import forgive_debt
from app.services.debt_service._proposal import (
    confirm_repayment_proposal,
    create_repayment_proposal,
    get_repayment_proposal_response,
    list_repayment_proposals,
    reject_repayment_proposal,
    withdraw_repayment_proposal,
)
from app.services.debt_service._query import (
    debt_response,
    get_debt,
    get_debt_response,
    get_participant_debt_response,
    list_debts,
)
from app.services.debt_service._repayment import (
    get_repayment_public_id_for_idempotency,
    record_repayment,
)
from app.services.debt_service._void import void_debt, void_repayment

__all__ = [
    "compute_paid",
    "compute_remaining",
    "compute_remaining_as_of",
    "confirm_repayment_proposal",
    "create_bill_split_debt",
    "create_debt",
    "create_repayment_proposal",
    "debt_response",
    "derive_status",
    "forgive_debt",
    "get_debt",
    "get_debt_response",
    "get_participant_debt_response",
    "get_repayment_proposal_response",
    "get_repayment_public_id_for_idempotency",
    "latest_fact_at",
    "list_debts",
    "list_repayment_proposals",
    "record_adjustment",
    "record_repayment",
    "reject_repayment_proposal",
    "void_debt",
    "void_repayment",
    "withdraw_repayment_proposal",
]
