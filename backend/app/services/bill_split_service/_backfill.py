"""ADR-0049 §4 / P3b: backfill the member Debt for bill splits accepted while the
Debt rollout was OFF, and the startup self-heal that drives it.

The rollout gate (``DEBT_ROLLOUT_ENABLED``) makes accepting a bill split create the
receiver's member Debt only when ON (``_transitions.accept_invitation``). Splits
accepted during the closed period therefore have NO member Debt. Flipping the flag
ON without catching up would leave the same kind of accepted split in two shapes —
"has a Debt" (accepted after the flip) vs "has no Debt" (accepted before) — a model
gap (model-invariant hardening P3b). This module closes it: it scans already-accepted
invitations missing their member Debt and creates exactly the Debt the accept
transaction would have, via the same ``create_bill_split_debt`` entry (byte-identical
shape, no drift).

The reconcile is gated on the SAME flag and is a deliberate self-heal: it runs at
startup ONLY when the rollout is ON, so it kicks in exactly when the operator flips
the flag (⑤b) and brings the historical accepted splits up to date. When the flag is
OFF it is a no-op — during the closed period an accepted split legitimately has no
Debt, so backfilling then would WRONGLY fabricate obligations. It is idempotent: the
missing-Debt query is empty once every accepted split has its Debt, so subsequent
startups are a cheap no-op (and ``uq_debts_source`` is the structural backstop a stray
double-insert would trip).
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import BillSplitInvitation, Debt
from app.services.debt_service import create_bill_split_debt

_logger = logging.getLogger(__name__)


def backfill_bill_split_debts(db: Session) -> int:
    """Create the missing member Debt for every already-accepted bill split that
    has none, and return the count created.

    Mirrors ``accept_invitation``'s §4 linkage exactly by calling the same
    ``create_bill_split_debt`` with the invitation's frozen fields, so a backfilled
    Debt is indistinguishable from one created inline at accept time (receiver owns
    it, ``i_owe`` the sender, the home-currency share ``amount_cents`` as principal,
    currency frozen from the invitation snapshot, ``source_id`` → the invitation).

    Idempotent: the query selects only ``accepted`` invitations with no
    ``bill_split`` Debt (correlated NOT EXISTS on ``(source_type, source_id)``), so a
    re-run after everything is backfilled creates nothing and returns 0. The list is
    materialised before the loop, so the inserts don't affect iteration. Commits once
    at the end (all inserts land together or none — a mid-batch failure rolls the
    whole batch back, leaving no partial state for the next run to puzzle over).
    """
    missing_debt = (
        select(Debt.id)
        .where(Debt.source_type == "bill_split")
        .where(Debt.source_id == BillSplitInvitation.public_id)
        .exists()
    )
    stmt = (
        select(BillSplitInvitation)
        .where(BillSplitInvitation.status == "accepted")
        .where(~missing_debt)
    )

    created = 0
    for inv in db.scalars(stmt).all():
        if inv.receiver_ledger_id is None:
            # Defensive: the accept claim binds receiver_ledger_id atomically, so an
            # accepted invitation always has its target ledger. Skip rather than
            # create a tenant-less Debt if a malformed row ever exists.
            continue
        create_bill_split_debt(
            db,
            ledger_id=inv.receiver_ledger_id,
            receiver_account_id=inv.receiver_account_id,
            sender_account_id=inv.sender_account_id,
            amount_cents=inv.amount_cents,
            home_currency_code=inv.home_currency_code,
            source_invitation_public_id=inv.public_id,
            event_time=inv.expense_time_snapshot,
        )
        created += 1
    if created:
        db.commit()
    return created


def reconcile_bill_split_debts_if_enabled() -> int:
    """Startup self-heal: when the Debt rollout is ON, backfill the member Debt for
    every historically-accepted bill split that is missing one (P3b). Returns the
    count created.

    No-op when the rollout is OFF — during the closed-rollout period an accepted
    split legitimately has no Debt, so backfilling then would fabricate obligations
    for the entire history. Gated on the flag so it runs exactly when the operator
    flips the rollout ON (⑤b) and is a cheap no-op on every subsequent start (the
    missing-Debt query is empty once reconciled). Uses its own session/transaction;
    a backfill failure surfaces at startup (data correctness, ADR-0049 §0) rather
    than committing half a catch-up.
    """
    if not get_settings().debt_rollout_enabled:
        return 0
    from app.database import SessionLocal

    with SessionLocal() as db:
        created = backfill_bill_split_debts(db)
    if created:
        _logger.info(
            "拆账 Debt 回填:为 %d 个历史已接受的拆账补建了 member Debt(DEBT_ROLLOUT 已开启)。",
            created,
        )
    return created
