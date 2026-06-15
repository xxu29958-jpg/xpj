"""ADR-0049 Debt read paths: ledger-scoped lookup + derived-fold response.

Slice 5 (§5.2) adds the ACCOUNT-scoped participant read: a member Debt's two
parties can live in different ledgers (a bill_split Debt is owned by the
receiver's ledger with the sender as the cross-ledger creditor), so the
repayment-proposal flow resolves a Debt by ledger membership unioned with the
member-counterparty relationship — the counterparty is the only cross-ledger
party, since the owner is always a member of the Debt's own ledger — not by
ledger scope alone. :func:`resolve_debt_for_participant` is that union resolver
and :func:`get_participant_debt_response` redacts the counterparty's ledger id
when the viewer is a participant-but-not-member (§5.2 "expose only the Debt
shell").
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Debt
from app.schemas import DebtListResponse, DebtResponse
from app.services.debt_service._fold import compute_paid, compute_remaining, derive_status


def participant_can_access(
    debt: Debt, *, ledger_id: str, account_id: int | None
) -> tuple[bool, bool]:
    """Return ``(is_ledger_member, is_cross_ledger_counterparty)`` for §5.2 access.

    ``is_ledger_member``: the actor's authenticated ledger IS the Debt's own
    ledger (the auth token proves membership of ``ledger_id``), the ordinary
    same-ledger path that already covers the debtor/owner side.

    ``is_cross_ledger_counterparty``: the actor's account is the Debt's member
    ``counterparty_account_id``. The cross-ledger party of a member Debt is
    ALWAYS the counterparty: a Debt's ``owner_account_id`` is created inside the
    Debt's own ledger (slice-1 manual create uses the actor's ledger; slice-4
    bill_split sets owner = the receiver who accepted into that ledger), so the
    owner is always a member and reaches the Debt via the membership branch using
    their OWN ledger token. Granting cross-ledger access through ``owner_account_id``
    would let the same account read its own Debt from an UNRELATED ledger context,
    breaking ledger-scoped existence hiding for external/owner-only Debt — so the
    cross-ledger grant is the counterparty's alone. An external Debt has a ``None``
    counterparty, so this is never true for it. The per-role debtor/creditor guard
    runs after access is granted and decides which side may actually act.

    The caller grants access when EITHER is true and uses ``is_ledger_member`` to
    decide whether the response keeps the (counterparty's) ledger id.
    """
    is_ledger_member = debt.tenant_id == ledger_id
    is_cross_ledger_counterparty = (
        account_id is not None and account_id == debt.counterparty_account_id
    )
    return is_ledger_member, is_cross_ledger_counterparty


def resolve_debt_for_participant(
    db: Session, *, public_id: str, ledger_id: str, account_id: int
) -> tuple[Debt, bool]:
    """Load a Debt visible to the actor as a ledger member OR the cross-ledger
    member counterparty.

    Returns ``(debt, is_ledger_member)``. ADR-0049 §5.2: the repayment-proposal
    flow is a two-party (debtor↔creditor) workflow whose parties can live in
    different ledgers, so it is scoped by ledger membership unioned with the
    member-counterparty relationship — NOT by ledger scope alone. A request that
    is neither a member of the Debt's ledger nor its counterparty gets
    ``debt_not_found`` (same 404 as a missing id — cross-ledger existence hiding,
    no enumeration leak; an owner reading from an unrelated ledger context still
    gets the ledger-scoped 404).
    """
    debt = db.scalar(select(Debt).where(Debt.public_id == public_id).limit(1))
    if debt is None:
        raise AppError("debt_not_found", status_code=404)
    is_ledger_member, is_counterparty = participant_can_access(
        debt, ledger_id=ledger_id, account_id=account_id
    )
    if not (is_ledger_member or is_counterparty):
        raise AppError("debt_not_found", status_code=404)
    return debt, is_ledger_member


def get_participant_debt_response(
    db: Session, *, public_id: str, ledger_id: str, account_id: int
) -> DebtResponse:
    """Debt response for a participant; redacts the ledger id for cross-ledger access.

    Same-ledger members get the full response. A participant who is NOT a member
    of the Debt's ledger (e.g. a bill_split creditor in another ledger confirming
    a repayment) gets only the Debt shell with ``ledger_id=None`` — §5.2 forbids
    exposing the counterparty's private ledger internals across accounts. Every
    other field (principal / remaining / paid / status / currency / row_version)
    is the obligation shell the participant needs to confirm or dispute.

    ``ledger_id`` is the ONLY field that needs redacting: ``owner_account_id`` is
    not in :class:`DebtResponse` at all; ``counterparty_account_id`` is the
    cross-ledger participant's OWN account id; ``source_id`` for a bill_split Debt
    is the invitation public_id the creditor themselves created — provenance both
    parties already hold, not the counterparty's ledger internal. (Invariant: a
    future ``source_type`` must keep ``source_id`` an identifier known to BOTH
    participants, or this shell would need to redact it too.)
    """
    debt, is_ledger_member = resolve_debt_for_participant(
        db, public_id=public_id, ledger_id=ledger_id, account_id=account_id
    )
    response = _debt_response_with_fold(db, debt)
    if is_ledger_member:
        return response
    return response.model_copy(update={"ledger_id": None})


def _debt_by_public_id(db: Session, *, tenant_id: str, public_id: str) -> Debt | None:
    return db.scalar(
        ledger_scoped_select(Debt, tenant_id).where(Debt.public_id == public_id).limit(1)
    )


def get_debt(db: Session, *, tenant_id: str, public_id: str) -> Debt:
    debt = _debt_by_public_id(db, tenant_id=tenant_id, public_id=public_id)
    if debt is None:
        raise AppError("debt_not_found", status_code=404)
    return debt


def debt_response(debt: Debt, *, remaining: int, paid: int) -> DebtResponse:
    return DebtResponse(
        public_id=debt.public_id,
        ledger_id=debt.tenant_id,
        direction=debt.direction,
        counterparty_type=debt.counterparty_type,
        counterparty_account_id=debt.counterparty_account_id,
        counterparty_label=debt.counterparty_label,
        principal_amount_cents=int(debt.principal_amount_cents),
        remaining_amount_cents=remaining,
        paid_amount_cents=paid,
        status=derive_status(debt, remaining),
        source_type=debt.source_type,
        source_id=debt.source_id,
        home_currency_code=debt.home_currency_code,
        original_currency_code=debt.original_currency_code,
        original_amount_minor=debt.original_amount_minor,
        exchange_rate_to_cny=debt.exchange_rate_to_cny,
        exchange_rate_date=debt.exchange_rate_date,
        exchange_rate_source=debt.exchange_rate_source,
        created_at=debt.created_at,
        updated_at=debt.updated_at,
        row_version=debt.row_version,
    )


def _debt_response_with_fold(db: Session, debt: Debt) -> DebtResponse:
    remaining = compute_remaining(db, debt)
    paid = compute_paid(db, debt)
    return debt_response(debt, remaining=remaining, paid=paid)


def get_debt_response(db: Session, *, tenant_id: str, public_id: str) -> DebtResponse:
    debt = get_debt(db, tenant_id=tenant_id, public_id=public_id)
    return _debt_response_with_fold(db, debt)


def list_debts(db: Session, *, tenant_id: str) -> DebtListResponse:
    statement = ledger_scoped_select(Debt, tenant_id).order_by(
        Debt.status.asc(),
        Debt.created_at.asc(),
        Debt.id.asc(),
    )
    debts = list(db.scalars(statement))
    return DebtListResponse(items=[_debt_response_with_fold(db, debt) for debt in debts])
