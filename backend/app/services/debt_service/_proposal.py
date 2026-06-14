"""ADR-0049 §3.2 MemberRepaymentProposal: the debtor↔creditor "I paid" handshake.

For a ``counterparty_type='member'`` Debt the debtor cannot directly commit a
``Repayment`` (that would unilaterally reduce the creditor's receivable, §5.2).
Instead the debtor *proposes* "I paid" — a pending intent that does NOT touch the
§2 fold — and the creditor confirms (full or partial), rejects, or the debtor
withdraws while it is still pending. Creating a new proposal supersedes the
existing pending one in the same transaction; the ``uq_mrp_one_pending_per_debt``
partial UNIQUE index is the §3.2 one-pending-per-Debt concurrency backstop.

Money (§2.2): the proposed amount freezes a backend-authoritative home
``proposed_amount_cents`` from the shared :func:`_money.freeze_home_amount` (the
same §2.2 definition Debt create + slice-2 repayment use); a foreign-currency
proposal keeps the original-currency provenance for display.

Only the CONFIRM path is fold-changing, so it goes through
:func:`~app.services.debt_service._serialize.lock_and_fold` (§2.1 parent-row
serialization + F8 overpay check from authoritative facts under the lock) and
commits one ``Repayment`` linked back via ``proposal_id``. Create / withdraw /
reject only mutate the proposal row's own lifecycle and never enter the fold.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Debt, MemberRepaymentProposal, Repayment
from app.schemas import (
    DebtResponse,
    MemberRepaymentProposalConfirmRequest,
    MemberRepaymentProposalCreateRequest,
    MemberRepaymentProposalListResponse,
    MemberRepaymentProposalRejectRequest,
    MemberRepaymentProposalResponse,
)
from app.services.debt_service._guards import (
    guard_actor_is_creditor,
    guard_actor_is_debtor,
    guard_member_debt,
    proposal_debtor_creditor,
)
from app.services.debt_service._money import freeze_home_amount
from app.services.debt_service._query import get_debt_response
from app.services.debt_service._serialize import lock_and_fold
from app.services.time_service import now_utc

# §3.2: a pending proposal expires 30 days after it is created if neither side
# acts. Mirrors the [[0042]] idempotency retention horizon (both bound a
# long-offline window) but is an independent business clock.
#
# Slice 3 observes expiry LAZILY: there is no background sweeper. A proposal's
# stored ``status`` stays ``pending`` until it is superseded / confirmed /
# rejected / withdrawn; the ``expires_at`` clock is only enforced at confirm time
# (``now_utc() > proposal.expires_at`` → ``repayment_proposal_expired`` 409), so an
# un-acted-on proposal past its TTL still reads ``pending`` but can no longer be
# confirmed. A status-flipping ``expired`` sweep, if ever wanted, is a later slice.
PROPOSAL_TTL = timedelta(days=30)


def _load_debt(db: Session, *, tenant_id: str, public_id: str) -> Debt:
    debt = db.scalar(
        ledger_scoped_select(Debt, tenant_id).where(Debt.public_id == public_id).limit(1)
    )
    if debt is None:
        raise AppError("debt_not_found", status_code=404)
    return debt


def _load_proposal(
    db: Session, *, debt_id: int, proposal_public_id: str
) -> MemberRepaymentProposal:
    proposal = db.scalar(
        select(MemberRepaymentProposal)
        .where(MemberRepaymentProposal.public_id == proposal_public_id)
        .where(MemberRepaymentProposal.debt_id == debt_id)
        .limit(1)
    )
    if proposal is None:
        raise AppError("repayment_proposal_not_found", status_code=404)
    return proposal


def _current_pending(db: Session, *, debt_id: int) -> MemberRepaymentProposal | None:
    return db.scalar(
        select(MemberRepaymentProposal)
        .where(MemberRepaymentProposal.debt_id == debt_id)
        .where(MemberRepaymentProposal.status == "pending")
        .limit(1)
    )


def _freeze_proposal_money(
    db: Session,
    *,
    tenant_id: str,
    payload: MemberRepaymentProposalCreateRequest,
    paid_at: datetime,
) -> dict:
    """Freeze the home ``proposed_amount_cents`` + original-currency provenance.

    Home path: ``proposed_amount_cents`` is the home amount directly. Foreign
    path: ``original_currency_code`` + ``original_amount`` (a major-units Decimal,
    the same shape ``DebtCreateRequest`` / ``RepaymentCreateRequest`` submit) are
    converted to a home amount via the shared §2.2 freeze. The two amount inputs
    are mutually exclusive (the freeze rejects mixing them). The freeze itself
    derives ``original_amount_minor`` from the major-units Decimal via the
    currency exponent, so the proposal row's provenance column is populated by the
    shared path — no caller-side minor↔major round-trip.

    Unlike Repayment (whose home_currency_code lives on the parent Debt), the
    proposal row stores ``home_currency_code`` itself, so keep it in the dict;
    only the amount key is renamed by the caller (amount_cents →
    proposed_amount_cents). The dict thus maps 1:1 onto the proposal columns:
    home_currency_code / original_currency_code / original_amount_minor /
    exchange_rate_to_cny / exchange_rate_date / exchange_rate_source (+ the
    popped amount_cents).
    """
    return freeze_home_amount(
        db,
        tenant_id=tenant_id,
        amount_cents=payload.proposed_amount_cents,
        original_currency=payload.original_currency_code,
        original_amount=payload.original_amount,
        # Freeze at the SAME paid_at the proposal row stores (payload.paid_at or
        # now_utc()), not the raw payload value — otherwise a paid_at-omitted
        # foreign proposal could freeze on a different FX date than it records,
        # diverging the home cents from the stored payment instant at a date edge.
        event_time=paid_at,
        amount_error="repayment_proposal_amount_invalid",
    )


def _latch_proposal_resolution(
    db: Session,
    proposal: MemberRepaymentProposal,
    *,
    status: str,
    actor_account_id: int,
    committed_repayment_id: int | None = None,
    confirmed_amount_cents: int | None = None,
) -> None:
    """Atomically move a proposal out of ``pending`` (DB predicate + rowcount).

    Withdraw / reject / confirm / supersede of the SAME proposal are adverse-
    interest writes that do NOT all share the parent-Debt lock (only confirm does,
    via :func:`lock_and_fold`). They serialise on the proposal row's own write
    lock, and the ``WHERE status='pending'`` predicate makes exactly one win:
    ``rowcount == 0`` means another party already resolved it, so a Python
    read-then-write here would clobber that resolution (e.g. a debtor withdraw
    overwriting a creditor's just-committed confirm). For confirm this raises
    inside the locked ``_mutate`` so the just-inserted ``Repayment`` rolls back
    with the transaction. Mirrors the bill-split guarded-flip idiom.
    """
    values: dict = {
        "status": status,
        "resolved_at": now_utc(),
        "resolved_by_account_id": actor_account_id,
    }
    if committed_repayment_id is not None:
        values["committed_repayment_id"] = committed_repayment_id
    if confirmed_amount_cents is not None:
        values["confirmed_amount_cents"] = confirmed_amount_cents
    result = db.execute(
        update(MemberRepaymentProposal)
        .where(MemberRepaymentProposal.id == proposal.id)
        .where(MemberRepaymentProposal.status == "pending")
        .values(**values)
    )
    if result.rowcount == 0:
        raise AppError("repayment_proposal_not_pending", status_code=409)
    db.expire(proposal)


def _resolve_superseded_pending(
    db: Session,
    *,
    debt_id: int,
    expected_public_id: str | None,
    actor_account_id: int,
    resolved_at: datetime,
) -> int | None:
    """Return the pending proposal id explicitly superseded by this create."""
    superseded = _current_pending(db, debt_id=debt_id)
    if superseded is None:
        if expected_public_id is not None:
            raise AppError("repayment_proposal_not_pending", status_code=409)
        return None
    if expected_public_id != superseded.public_id:
        raise AppError("repayment_proposal_already_pending", status_code=409)
    flipped = db.execute(
        update(MemberRepaymentProposal)
        .where(MemberRepaymentProposal.id == superseded.id)
        .where(MemberRepaymentProposal.status == "pending")
        .values(
            status="superseded",
            resolved_at=resolved_at,
            resolved_by_account_id=actor_account_id,
        )
    )
    if not flipped.rowcount:
        raise AppError("repayment_proposal_not_pending", status_code=409)
    return superseded.id


def create_repayment_proposal(
    db: Session,
    *,
    tenant_id: str,
    actor_account_id: int,
    public_id: str,
    payload: MemberRepaymentProposalCreateRequest,
    idempotency_key: str,
    commit: bool = True,
) -> MemberRepaymentProposalResponse:
    """Create a pending member repayment proposal, or explicitly supersede one.

    Does NOT touch the §2 fold — a pending proposal is an intent, not a fact.
    ``commit=False`` lets the route commit the insert together with the [[0042]]
    idempotency-success record in one transaction.
    """
    debt = _load_debt(db, tenant_id=tenant_id, public_id=public_id)
    if debt.status == "voided":
        raise AppError("debt_already_voided", status_code=409)
    guard_member_debt(debt)
    guard_actor_is_debtor(debt, actor_account_id)
    _, creditor_account_id = proposal_debtor_creditor(debt)

    paid_at = payload.paid_at or now_utc()
    money = _freeze_proposal_money(db, tenant_id=tenant_id, payload=payload, paid_at=paid_at)
    proposed_amount_cents = money.pop("amount_cents")

    # Replacement must name the pending proposal the client saw; the partial
    # unique index remains the backstop for concurrent first creates.
    now = now_utc()
    supersedes_proposal_id = _resolve_superseded_pending(
        db,
        debt_id=debt.id,
        expected_public_id=payload.supersedes_proposal_public_id,
        actor_account_id=actor_account_id,
        resolved_at=now,
    )
    proposal = MemberRepaymentProposal(
        debt_id=debt.id,
        debtor_account_id=actor_account_id,
        creditor_account_id=creditor_account_id,
        proposed_by_account_id=actor_account_id,
        proposed_amount_cents=proposed_amount_cents,
        paid_at=paid_at,
        note=(payload.note or "").strip() or None,
        status="pending",
        created_at=now,
        expires_at=payload.expires_at or (now + PROPOSAL_TTL),
        supersedes_proposal_id=supersedes_proposal_id,
        idempotency_key=idempotency_key,
        **money,
    )
    db.add(proposal)
    try:
        # SAVEPOINT so a partial-index unique violation (a concurrent create that
        # already inserted a pending row) rolls back only this insert, not the
        # caller's outer transaction — mirrors the idempotency claim's
        # begin_nested() pattern.
        with db.begin_nested():
            db.flush()
    except IntegrityError as exc:
        raise AppError("repayment_proposal_already_pending", status_code=409) from exc

    if commit:
        db.commit()
        db.refresh(proposal)
    return proposal_response(db, proposal)


def withdraw_repayment_proposal(
    db: Session,
    *,
    tenant_id: str,
    actor_account_id: int,
    public_id: str,
    proposal_public_id: str,
    idempotency_key: str,
    commit: bool = True,
) -> MemberRepaymentProposalResponse:
    """Debtor withdraws their own still-pending proposal (does NOT touch the fold)."""
    debt = _load_debt(db, tenant_id=tenant_id, public_id=public_id)
    proposal = _load_proposal(db, debt_id=debt.id, proposal_public_id=proposal_public_id)
    guard_actor_is_debtor(debt, actor_account_id)
    _latch_proposal_resolution(
        db, proposal, status="withdrawn", actor_account_id=actor_account_id
    )
    if commit:
        db.commit()
    return proposal_response(db, proposal)


def _confirmed_amount(
    proposal: MemberRepaymentProposal,
    payload: MemberRepaymentProposalConfirmRequest,
    remaining_before: int,
) -> int:
    """Resolve + validate the confirmed amount under the §2.1 lock.

    ``None`` confirms the full proposed amount. ``0 < amount <= proposed`` (a
    partial confirm is allowed); else ``repayment_proposal_amount_invalid`` 422.
    ``amount > remaining_before`` is an overpay (F8) → ``debt_overpay_rejected``.
    """
    proposed = int(proposal.proposed_amount_cents)
    amount = (
        payload.confirmed_amount_cents
        if payload.confirmed_amount_cents is not None
        else proposed
    )
    if amount <= 0 or amount > proposed:
        raise AppError("repayment_proposal_amount_invalid", status_code=422)
    # §3.1 / F8: a repayment that would push remaining below 0 is rejected inside
    # the serialized section, never silently clamped.
    if amount > remaining_before:
        raise AppError("debt_overpay_rejected", status_code=422)
    return amount


def _commit_confirmation(
    db: Session,
    *,
    proposal: MemberRepaymentProposal,
    debt_id: int,
    amount: int,
    actor_account_id: int,
    idempotency_key: str,
) -> None:
    """Insert the committed ``Repayment`` and latch the proposal's resolution.

    A full confirm (``amount == proposed``) copies the proposal's frozen
    provenance onto the repayment; a partial confirm records a home-only
    repayment (original_* null — a partial home amount has no faithful
    original-currency split).
    """
    is_full = amount == int(proposal.proposed_amount_cents)
    repayment = Repayment(
        debt_id=debt_id,
        amount_cents=amount,
        original_currency_code=proposal.original_currency_code if is_full else None,
        original_amount_minor=proposal.original_amount_minor if is_full else None,
        exchange_rate_to_cny=proposal.exchange_rate_to_cny if is_full else None,
        exchange_rate_date=proposal.exchange_rate_date if is_full else None,
        exchange_rate_source=proposal.exchange_rate_source if is_full else None,
        paid_at=proposal.paid_at,
        actor_account_id=actor_account_id,
        proposal_id=proposal.id,
        idempotency_key=idempotency_key,
    )
    db.add(repayment)
    db.flush()
    # Guarded flip: a debtor withdraw (which does NOT take the parent-Debt lock)
    # could have resolved this proposal between the under-lock re-fetch and here;
    # ``WHERE status='pending'`` rowcount==0 then raises not_pending and rolls the
    # just-inserted Repayment back with the transaction (no clobber, no orphan fact).
    _latch_proposal_resolution(
        db,
        proposal,
        status="confirmed" if is_full else "partially_confirmed",
        actor_account_id=actor_account_id,
        committed_repayment_id=repayment.id,
        confirmed_amount_cents=amount,
    )


def confirm_repayment_proposal(
    db: Session,
    *,
    tenant_id: str,
    actor_account_id: int,
    public_id: str,
    proposal_public_id: str,
    payload: MemberRepaymentProposalConfirmRequest,
    idempotency_key: str,
    commit: bool = True,
) -> DebtResponse | None:
    """Creditor confirms a proposal — commits one ``Repayment`` (fold-changing).

    The §2.1 parent-Debt serialization (FOR UPDATE + bump) and the F8 overpay
    check run inside :func:`lock_and_fold`; the proposal is re-fetched under the
    lock so its pending/expiry checks see authoritative state.
    """
    debt = _load_debt(db, tenant_id=tenant_id, public_id=public_id)
    guard_actor_is_creditor(debt, actor_account_id)

    def _mutate(locked_debt: Debt, remaining_before: int) -> None:
        proposal = _load_proposal(
            db, debt_id=locked_debt.id, proposal_public_id=proposal_public_id
        )
        if proposal.status != "pending":
            raise AppError("repayment_proposal_not_pending", status_code=409)
        if now_utc() > proposal.expires_at:
            raise AppError("repayment_proposal_expired", status_code=409)
        amount = _confirmed_amount(proposal, payload, remaining_before)
        _commit_confirmation(
            db,
            proposal=proposal,
            debt_id=locked_debt.id,
            amount=amount,
            actor_account_id=actor_account_id,
            idempotency_key=idempotency_key,
        )

    lock_and_fold(
        db,
        tenant_id=tenant_id,
        public_id=public_id,
        expected_row_version=payload.expected_row_version,
        mutate=_mutate,
    )
    # Mirror slice-2 ``record_repayment``'s commit boundary exactly: only the
    # ``commit=True`` direct-caller path commits + expires here. ``lock_and_fold``
    # leaves the parent ``row_version`` bump as a pending SQL expression on the
    # in-session Debt; with ``commit=False`` the ROUTE owns the post-commit
    # ``expire_all`` + re-serialise (it commits the [[0042]] success record in the
    # same transaction first), so this service must NOT ``expire_all`` early — that
    # would force a premature reload that diverges from the slice-2 fact services.
    if not commit:
        return None
    db.commit()
    db.expire_all()
    return get_debt_response(db, tenant_id=tenant_id, public_id=public_id)


def reject_repayment_proposal(
    db: Session,
    *,
    tenant_id: str,
    actor_account_id: int,
    public_id: str,
    proposal_public_id: str,
    payload: MemberRepaymentProposalRejectRequest,
    idempotency_key: str,
    commit: bool = True,
) -> MemberRepaymentProposalResponse:
    """Creditor rejects a still-pending proposal (does NOT touch the fold)."""
    debt = _load_debt(db, tenant_id=tenant_id, public_id=public_id)
    proposal = _load_proposal(db, debt_id=debt.id, proposal_public_id=proposal_public_id)
    guard_actor_is_creditor(debt, actor_account_id)
    _latch_proposal_resolution(
        db, proposal, status="rejected", actor_account_id=actor_account_id
    )
    if commit:
        db.commit()
    return proposal_response(db, proposal)


def get_repayment_proposal_response(
    db: Session, *, tenant_id: str, public_id: str, proposal_public_id: str
) -> MemberRepaymentProposalResponse:
    """Re-serialise one proposal's canonical state (used by [[0042]] HIT replay).

    Ledger-scoped via the parent Debt, then the proposal must belong to that Debt
    (existence is hidden as not-found otherwise), so a HIT/replay cannot leak a
    cross-ledger proposal.
    """
    debt = _load_debt(db, tenant_id=tenant_id, public_id=public_id)
    proposal = _load_proposal(db, debt_id=debt.id, proposal_public_id=proposal_public_id)
    return proposal_response(db, proposal)


def list_repayment_proposals(
    db: Session, *, tenant_id: str, public_id: str
) -> MemberRepaymentProposalListResponse:
    """List a member Debt's repayment proposals (read; newest first)."""
    debt = _load_debt(db, tenant_id=tenant_id, public_id=public_id)
    proposals = list(
        db.scalars(
            select(MemberRepaymentProposal)
            .where(MemberRepaymentProposal.debt_id == debt.id)
            .order_by(
                MemberRepaymentProposal.created_at.desc(),
                MemberRepaymentProposal.id.desc(),
            )
        )
    )
    return MemberRepaymentProposalListResponse(
        items=[proposal_response(db, proposal) for proposal in proposals]
    )


def _public_id_for(db: Session, model: type, internal_id: int | None) -> str | None:
    """Resolve a linked row's ``public_id`` by internal id (or None)."""
    if internal_id is None:
        return None
    return db.scalar(select(model.public_id).where(model.id == internal_id).limit(1))


def proposal_response(
    db: Session, proposal: MemberRepaymentProposal
) -> MemberRepaymentProposalResponse:
    """Map a proposal to its public response — internal int ids → public_ids (§3)."""
    debt_public_id = db.scalar(
        select(Debt.public_id).where(Debt.id == proposal.debt_id).limit(1)
    )
    return MemberRepaymentProposalResponse(
        public_id=proposal.public_id,
        debt_public_id=debt_public_id,
        status=proposal.status,
        proposed_amount_cents=int(proposal.proposed_amount_cents),
        confirmed_amount_cents=proposal.confirmed_amount_cents,
        home_currency_code=proposal.home_currency_code,
        original_currency_code=proposal.original_currency_code,
        original_amount_minor=proposal.original_amount_minor,
        paid_at=proposal.paid_at,
        note=proposal.note,
        expires_at=proposal.expires_at,
        created_at=proposal.created_at,
        resolved_at=proposal.resolved_at,
        supersedes_proposal_public_id=_public_id_for(
            db, MemberRepaymentProposal, proposal.supersedes_proposal_id
        ),
        committed_repayment_public_id=_public_id_for(
            db, Repayment, proposal.committed_repayment_id
        ),
    )
