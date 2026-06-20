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

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Account, Debt, LedgerMember
from app.schemas import DebtListResponse, DebtResponse
from app.services.debt_service._fold import (
    compute_paid,
    compute_remaining,
    derive_status,
    has_forgiveness,
)
from app.services.debt_service._guards import proposal_debtor_creditor
from app.services.debt_service._installment import installment_payoff_date


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
    # §3.2: the server is the authority for the viewer's debtor/creditor role (the client can't
    # derive it — see DebtResponse.viewer_is_debtor). Cross-ledger reads additionally redact the
    # counterparty's ledger id (§5.2).
    viewer_is_debtor = _viewer_is_debtor(debt, account_id)
    update: dict = {"viewer_is_debtor": viewer_is_debtor}
    if not is_ledger_member:
        update["ledger_id"] = None
        # ⑤c list↔detail consistency: a cross-ledger CREDITOR's receivables list shows the
        # debtor's name in counterparty_label; surface the same name here so opening the
        # detail doesn't fall back to the generic member label. Only the creditor side
        # (viewer_is_debtor is False) — the debtor's own payable view stays generic (the
        # counterparty there is the creditor, framed by the communal headline, not named).
        if viewer_is_debtor is False:
            debtor_name = _owner_display_names(db, {debt.owner_account_id}).get(
                debt.owner_account_id
            )
            if debtor_name:
                update["counterparty_label"] = debtor_name
    return response.model_copy(update=update)


def _owner_display_names(db: Session, owner_account_ids: set[int]) -> dict[int, str]:
    """Batch-resolve ``{account_id: display_name}`` for the given debtor (owner) accounts.

    One ``WHERE id IN (...)`` (no N+1) for the receivables list; blank names are omitted
    so the caller leaves ``counterparty_label`` ``None`` and the renderers fall back to the
    generic member label (``Account.display_name`` is NOT NULL, so this is belt-and-suspenders).
    The debtor's name is shared provenance — the creditor is the bill_split sender who named
    this receiver at invite time — so surfacing it does NOT cross the §5.2/ADR-0029 boundary
    (which redacts the debtor's LEDGER, not their identity).
    """
    if not owner_account_ids:
        return {}
    rows = db.execute(
        select(Account.id, Account.display_name).where(Account.id.in_(owner_account_ids))
    ).all()
    return {acc_id: name for acc_id, name in rows if (name or "").strip()}


def _viewer_is_debtor(debt: Debt, account_id: int) -> bool | None:
    """The viewer's role on a member Debt: True=debtor, False=creditor, None=not a party.

    ``None`` for an external Debt (no member counterparty) and for a same-ledger member who is
    neither the owner nor the counterparty (a third member viewing the obligation). The per-role
    guards (§3.2) still enforce who may actually act; this only drives which actions the UI offers.
    """
    if debt.counterparty_type != "member":
        return None
    debtor_account_id, creditor_account_id = proposal_debtor_creditor(debt)
    if account_id == debtor_account_id:
        return True
    if account_id == creditor_account_id:
        return False
    return None


def _debt_by_public_id(db: Session, *, tenant_id: str, public_id: str) -> Debt | None:
    return db.scalar(
        ledger_scoped_select(Debt, tenant_id).where(Debt.public_id == public_id).limit(1)
    )


def get_debt(db: Session, *, tenant_id: str, public_id: str) -> Debt:
    debt = _debt_by_public_id(db, tenant_id=tenant_id, public_id=public_id)
    if debt is None:
        raise AppError("debt_not_found", status_code=404)
    return debt


def debt_response(
    debt: Debt, *, remaining: int, paid: int, is_forgiven: bool = False
) -> DebtResponse:
    # §B: gate ALL schedule fields on debt_kind. ``set_debt_kind`` leaves the columns populated when
    # reclassifying AWAY from installment, so reading them raw would expose stale installment metadata
    # on a now-revolving/one_off debt. Gating the whole shape (count + period + the already-gated
    # payoff date) keeps a non-installment response clean — matching the schema's "None for
    # non-installment" contract.
    is_installment = debt.debt_kind == "installment"
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
        debt_kind=debt.debt_kind,
        # §B: the stored schedule + the derived deterministic payoff date, all None for non-installment.
        installment_count=debt.installment_count if is_installment else None,
        installment_period_months=debt.installment_period_months if is_installment else None,
        installment_payoff_date=installment_payoff_date(debt),
        home_currency_code=debt.home_currency_code,
        original_currency_code=debt.original_currency_code,
        original_amount_minor=debt.original_amount_minor,
        exchange_rate_to_cny=debt.exchange_rate_to_cny,
        exchange_rate_date=debt.exchange_rate_date,
        exchange_rate_source=debt.exchange_rate_source,
        created_at=debt.created_at,
        updated_at=debt.updated_at,
        row_version=debt.row_version,
        is_forgiven=is_forgiven,
    )


def _debt_response_with_fold(db: Session, debt: Debt) -> DebtResponse:
    remaining = compute_remaining(db, debt)
    paid = compute_paid(db, debt)
    # §3.7 / §4: a forgiven Debt is a CLEARED Debt that carries a DebtForgiveness fact —
    # distinct from a repayment-cleared one. Only check the fact when the fold says cleared
    # (open/voided are never "forgiven"), so a stray forgiveness on a later-reopened Debt
    # does not mislabel it.
    is_forgiven = derive_status(debt, remaining) == "cleared" and has_forgiveness(db, debt.id)
    return debt_response(debt, remaining=remaining, paid=paid, is_forgiven=is_forgiven)


def get_debt_response(db: Session, *, tenant_id: str, public_id: str) -> DebtResponse:
    debt = get_debt(db, tenant_id=tenant_id, public_id=public_id)
    return _debt_response_with_fold(db, debt)


def list_debts(
    db: Session, *, tenant_id: str, viewer_account_id: int | None = None
) -> DebtListResponse:
    """Ledger-scoped Debt list. With ``viewer_account_id`` each row carries the
    server-authoritative ``viewer_is_debtor`` for that viewer (§3.2).

    The list cannot frame a MEMBER debt from the stored ``direction`` alone:
    ``direction`` is owner-relative, and a bill_split member Debt's owner is the
    receiver who accepted the split — a *writer member* of the ledger, not
    necessarily the ledger owner (``accept_invitation`` only requires write
    membership). So one ledger can hold a member Debt whose owner is neither the
    loopback owner-console viewer nor the web-session viewer; rendering owner-relative
    ``direction`` as-is would mis-frame "you fronted this for me" onto a third party.
    The viewer's debtor/creditor role is therefore computed PER ROW from the viewer's
    account — the SAME server-authoritative derivation the detail uses
    (:func:`_viewer_is_debtor`), NOT a client-side guess (red-line ⑥). External rows
    stay ``None`` (no member counterparty). A ``None`` viewer (e.g. a ledger with no
    active owner on loopback) leaves every role ``None`` and the list degrades to the
    neutral third-party framing.
    """
    statement = ledger_scoped_select(Debt, tenant_id).order_by(
        Debt.status.asc(),
        Debt.created_at.asc(),
        Debt.id.asc(),
    )
    debts = list(db.scalars(statement))
    items: list[DebtResponse] = []
    for debt in debts:
        response = _debt_response_with_fold(db, debt)
        if viewer_account_id is not None:
            response = response.model_copy(
                update={"viewer_is_debtor": _viewer_is_debtor(debt, viewer_account_id)}
            )
        items.append(response)
    return DebtListResponse(items=items)


def list_member_receivables_for_account(
    db: Session, *, account_id: int
) -> DebtListResponse:
    """Account-scoped list of the CROSS-LEDGER member Debts this account is the
    creditor of — "money owed to me" that the ledger-scoped :func:`list_debts`
    cannot surface (creditor-discovery gap, ADR-0049 P3b / ⑤c).

    A bill_split member Debt lives in the DEBTOR's ledger (``tenant_id`` = the
    receiver's chosen ledger, ``owner`` = receiver = debtor, member ``counterparty``
    = sender = creditor, ``direction='i_owe'``). The debtor sees it in their own
    ``list_debts``; the creditor is a member of a DIFFERENT ledger and has no
    ledger-scoped path to it. This returns every member Debt where the account is
    the counterparty-CREDITOR (``direction='i_owe'`` so the counterparty is the
    creditor — :func:`proposal_debtor_creditor`; an ``owed_to_me`` member Debt would
    make the counterparty the DEBTOR, a payable, correctly excluded) AND whose
    ledger the account is NOT an ACTIVE member of (a same-ledger member Debt the
    account already sees in ``list_debts`` is not duplicated here; the owner-creditor
    case is never cross-ledger since the owner is always a member of the Debt's ledger).
    "Active" matches the auth membership definition so a soft-removed creditor — who
    can no longer get a token for that ledger — still sees the receivable here.

    Shell-redacted (§5.2 / ADR-0029 privacy): ``ledger_id`` is always ``None`` — the
    creditor must never learn which ledger the debtor parked the obligation in (the
    receiver's private ledger choice). ``viewer_is_debtor`` is ``False`` for every
    row (the viewer is the creditor by construction). Every other field (principal /
    remaining / paid / status / currency / source) is the obligation shell the
    creditor needs to track the receivable.
    """
    # ACTIVE membership only (disabled_at IS NULL) — must match the auth path
    # (identity_service._auth filters disabled_at IS NULL to build the AuthContext that
    # scopes list_debts). A creditor SOFT-REMOVED from the debtor's ledger has a
    # disabled LedgerMember row but cannot obtain a token for that ledger, so they can
    # NOT see the Debt via list_debts — counting that stale membership here would hide a
    # genuinely-unreachable receivable. (A still-ACTIVE member of the Debt's ledger CAN
    # reach it by viewing that ledger, so it is intentionally excluded from this
    # cross-ledger lens.)
    viewer_is_member = (
        select(LedgerMember.id)
        .where(LedgerMember.ledger_id == Debt.tenant_id)
        .where(LedgerMember.account_id == account_id)
        .where(LedgerMember.disabled_at.is_(None))
        .exists()
    )
    statement = (
        select(Debt)
        # counterparty_type=='member' is belt-and-suspenders: ck_debts_member_has_account
        # makes counterparty_account_id NON-NULL iff member, so the account-id match below
        # already restricts to member rows (an external Debt has a NULL counterparty). Kept
        # for explicit intent.
        .where(Debt.counterparty_type == "member")
        .where(Debt.direction == "i_owe")
        .where(Debt.counterparty_account_id == account_id)
        .where(~viewer_is_member)
        .order_by(Debt.status.asc(), Debt.created_at.asc(), Debt.id.asc())
    )
    debts = list(db.scalars(statement))
    # Who owes the creditor: the debtor is the Debt OWNER (the bill_split receiver). The
    # creditor must see WHO, so surface the debtor's live display name in counterparty_label
    # (one batched lookup, no N+1). The stored counterparty_account_id is the creditor's own
    # id and direction is owner-relative 'i_owe' — both left UNTOUCHED so the row stays
    # byte-identical to the detail framing (list↔detail consistency); only the label is added.
    debtor_names = _owner_display_names(db, {debt.owner_account_id for debt in debts})
    items: list[DebtResponse] = []
    for debt in debts:
        response = _debt_response_with_fold(db, debt)
        update: dict = {
            "viewer_is_debtor": _viewer_is_debtor(debt, account_id),
            "ledger_id": None,
        }
        debtor_name = debtor_names.get(debt.owner_account_id)
        if debtor_name:
            update["counterparty_label"] = debtor_name
        items.append(response.model_copy(update=update))
    return DebtListResponse(items=items)


def count_open_external_debts(db: Session, tenant_ids: list[str]) -> dict[str, int]:
    """Per-ledger count of OPEN external Debts (owner-overview aggregate, slice 5).

    Counts debts whose stored lifecycle ``status='open'`` and
    ``counterparty_type='external'``, grouped by ``tenant_id`` so an N-ledger owner
    dashboard resolves in ONE query (mirrors the ``_ledger_console`` grouped-count
    pattern). The stored ``status`` is the latch maintained at every fold-changing
    write (``lock_and_fold`` re-derives + persists it from the §2 fold), so an
    at-rest snapshot count matches the derived status without a per-debt fold:
    ``open`` excludes both ``cleared`` (remaining 0) and ``voided`` (DebtVoid latch).

    External-only by design (ADR-0049 §7.0 / slice 5): a member Debt is a
    relationship surface, never an owner-ops counter — the overview shows aggregate
    counts only, NO per-user / per-counterparty / who-owes-who detail. Returns a dict
    keyed by tenant; ledgers with no open external debt are absent (caller defaults 0).
    """
    if not tenant_ids:
        return {}
    rows = db.execute(
        select(Debt.tenant_id, func.count())
        .where(Debt.tenant_id.in_(tenant_ids))
        .where(Debt.counterparty_type == "external")
        .where(Debt.status == "open")
        .group_by(Debt.tenant_id)
    ).all()
    return {tenant_id: int(count) for tenant_id, count in rows}
