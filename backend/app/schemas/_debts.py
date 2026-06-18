"""ADR-0049 Debt domain CRUD payloads.

Slice 1: create / list / get. Slice 2 adds the fold-changing write requests
(repayment / adjustment / repayment-void / debt-void). Every write request
carries ``expected_row_version`` (§3.6 — part of the [[0042]] fingerprint and
the §2.1 stale-intent check) and replies with the fold-after ``DebtResponse``
so the client gets the fresh ``row_version`` for its next ``expected``.

Slice 3 adds the member ``MemberRepaymentProposal`` workflow (§3.2): the debtor
proposes "I paid" (create, no parent CAS — there is no fold change yet), the
creditor confirms (full or partial — fold-changing, so the confirm request
carries ``expected_row_version``) or rejects, and the debtor withdraws. Confirm
replies with the fold-after ``DebtResponse``; the other three reply with the
proposal's own ``MemberRepaymentProposalResponse`` (public_id only, never an
internal int id — §3).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.services.time_service import to_iso

__all__ = [
    "DebtAdjustmentCreateRequest",
    "DebtCreateRequest",
    "DebtForgiveCreateRequest",
    "DebtListResponse",
    "DebtResponse",
    "DebtVoidCreateRequest",
    "MemberRepaymentProposalConfirmRequest",
    "MemberRepaymentProposalCreateRequest",
    "MemberRepaymentProposalListResponse",
    "MemberRepaymentProposalRejectRequest",
    "MemberRepaymentProposalResponse",
    "MemberRepaymentProposalWithdrawRequest",
    "RepaymentCreateRequest",
    "RepaymentCreateResponse",
    "RepaymentVoidCreateRequest",
]


class DebtCreateRequest(BaseModel):
    """Create one external/manual Debt (ADR-0049 §2 / §5.1).

    ``principal_amount_cents`` is the home-currency principal for a home-currency
    Debt. For a foreign-currency Debt the client submits ``original_currency`` +
    ``original_amount`` (+ optional ``event_time``); the backend freezes the
    home principal from the [[0027]] snapshot and rejects the request when the
    rate is still pending (§2.2). Clients MUST NOT submit exchange rates or
    compute home amounts.
    """

    model_config = ConfigDict(extra="forbid")

    direction: str
    counterparty_type: str
    counterparty_account_id: int | None = None
    counterparty_label: str | None = Field(default=None, max_length=255)
    principal_amount_cents: int | None = Field(default=None, gt=0)
    original_currency: str | None = Field(default=None, min_length=3, max_length=3)
    original_amount: Decimal | None = Field(default=None, gt=0)
    event_time: datetime | None = None
    source_type: str = "manual"


class DebtResponse(BaseModel):
    public_id: str
    # ADR-0049 §5.2: optional so a cross-ledger participant view can redact it.
    # A member Debt's two parties may live in different ledgers (a bill_split Debt
    # is owned by the receiver's ledger with the sender as the cross-ledger
    # creditor). When the viewer is a participant but NOT a member of the Debt's
    # ledger, the response is the Debt shell only and ``ledger_id`` is ``None`` —
    # the counterparty's ledger id is a private internal. Same-ledger reads keep it.
    ledger_id: str | None = None
    direction: str
    counterparty_type: str
    counterparty_account_id: int | None = None
    counterparty_label: str | None = None
    principal_amount_cents: int
    remaining_amount_cents: int
    paid_amount_cents: int
    status: str
    source_type: str
    source_id: str | None = None
    home_currency_code: str
    original_currency_code: str | None = None
    original_amount_minor: int | None = None
    exchange_rate_to_cny: Decimal | None = None
    exchange_rate_date: datetime | None = None
    exchange_rate_source: str | None = None
    created_at: datetime
    updated_at: datetime
    row_version: int
    # ADR-0049 §3.2 / §5.2 (slice 8d): the SERVER-authoritative debtor/creditor role for the
    # viewer of a member Debt — the client cannot derive it (it does not know its own account id,
    # and ledger membership does not distinguish the same-ledger owner from a same-ledger member
    # counterparty). ``True`` = viewer is the debtor (may propose / withdraw); ``False`` = creditor
    # (may confirm / reject); ``None`` for an external Debt, a non-participant member, or a fact route
    # without participant context. Both ``get_participant_debt_response`` (detail) and ``list_debts``
    # with a ``viewer_account_id`` (the list, computed per row for the viewer — slice 1A communal rows)
    # populate it server-side; the client never derives it.
    viewer_is_debtor: bool | None = None
    # ADR-0049 §3.7 / §4 (slice 8e-3): True when this Debt was CLEARED by a creditor forgiveness
    # ("算了，不用还了") rather than fully repaid — i.e. status=='cleared' AND a DebtForgiveness fact
    # exists. The client renders a "被请客/请客" headline instead of the generic "两清" and the §5.6
    # celebration fork skips the settle confetti for it (it's a gift, not a settle-to-zero). Always
    # False for open / voided / repayment-cleared Debt; computed in _debt_response_with_fold.
    is_forgiven: bool = False

    @field_serializer("created_at", "updated_at", "exchange_rate_date")
    def serialize_debt_datetime(self, value: datetime | None) -> str | None:
        return to_iso(value)


class DebtListResponse(BaseModel):
    items: list[DebtResponse]


class RepaymentCreateResponse(DebtResponse):
    """Fold-after Debt response plus the committed repayment id for void flows."""

    repayment_public_id: str


class RepaymentCreateRequest(BaseModel):
    """Record one committed repayment fact (ADR-0049 §3.1).

    Home-currency repayment submits ``amount_cents``. A foreign-currency
    repayment submits ``original_currency`` + ``original_amount`` (+ optional
    ``paid_at``); the backend freezes the home ``amount_cents`` from the [[0027]]
    snapshot for ``paid_at`` and rejects when the rate is pending (§2.2). The two
    amount inputs are mutually exclusive. ``expected_row_version`` is the §2.1
    stale-intent token + §3.6 fingerprint component. The debtor "I paid"
    proposal (``proposal_id``) is slice 3 and is NOT accepted here.
    """

    model_config = ConfigDict(extra="forbid")

    amount_cents: int | None = Field(default=None, gt=0)
    original_currency: str | None = Field(default=None, min_length=3, max_length=3)
    original_amount: Decimal | None = Field(default=None, gt=0)
    paid_at: datetime | None = None
    expected_row_version: int


class DebtAdjustmentCreateRequest(BaseModel):
    """Record one signed principal-like correction (ADR-0049 §3.3).

    ``amount_cents`` is a signed home-currency delta (may be negative to lower
    ``remaining``; never to push it below 0). ``reason`` is required.
    ``expected_row_version`` is the §2.1 stale-intent token + §3.6 fingerprint
    component.
    """

    model_config = ConfigDict(extra="forbid")

    amount_cents: int
    reason: str = Field(min_length=1, max_length=500)
    expected_row_version: int


class RepaymentVoidCreateRequest(BaseModel):
    """Void one mistaken repayment (ADR-0049 §3.4).

    ``repayment_public_id`` identifies the repayment to void; it must belong to
    this Debt. ``reason`` is required. The original repayment row is never
    deleted (the void is append-only and excludes it from the fold).
    """

    model_config = ConfigDict(extra="forbid")

    repayment_public_id: str = Field(min_length=1, max_length=36)
    reason: str = Field(min_length=1, max_length=500)
    expected_row_version: int


class DebtVoidCreateRequest(BaseModel):
    """Void an entire Debt (ADR-0049 §3.5). ``reason`` is required."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)
    expected_row_version: int


class DebtForgiveCreateRequest(BaseModel):
    """Creditor forgives a member Debt's remaining (ADR-0049 §3.7 / §4, slice 8e-3).

    A one-sided creditor waiver ("算了，不用还了"): no amount and no reason — the
    forgiven amount is the ``remaining_before`` the backend snapshots under the §2.1
    lock, and forgiveness needs no justification (it benefits the debtor only).
    ``expected_row_version`` is the §2.1 stale-intent token + §3.6 fingerprint component
    (REQUIRED — this is fold-changing).
    """

    model_config = ConfigDict(extra="forbid")

    expected_row_version: int


class MemberRepaymentProposalCreateRequest(BaseModel):
    """Debtor "I paid" proposal for a member Debt (ADR-0049 §3.2).

    Home-currency proposal submits ``proposed_amount_cents``. A foreign-currency
    proposal submits ``original_currency_code`` + ``original_amount`` (a
    major-units Decimal, exactly like ``DebtCreateRequest`` / ``RepaymentCreateRequest``)
    (+ optional ``paid_at``); the backend freezes the home ``proposed_amount_cents``
    from the [[0027]] snapshot for ``paid_at`` and rejects when the rate is
    pending (§2.2). Creating a proposal does NOT change the fold (it is a pending
    intent, not a fact), so there is no ``expected_row_version`` — the parent CAS
    happens only on confirm. To replace an existing pending proposal, the client
    must name the pending proposal it saw via ``supersedes_proposal_public_id``;
    otherwise a delayed request could overwrite a newer unseen proposal.
    """

    model_config = ConfigDict(extra="forbid")

    proposed_amount_cents: int | None = Field(default=None, gt=0)
    original_currency_code: str | None = Field(default=None, min_length=3, max_length=3)
    original_amount: Decimal | None = Field(default=None, gt=0)
    paid_at: datetime | None = None
    note: str | None = Field(default=None, max_length=500)
    expires_at: datetime | None = None
    supersedes_proposal_public_id: str | None = Field(default=None, min_length=1, max_length=36)


class MemberRepaymentProposalConfirmRequest(BaseModel):
    """Creditor confirms a member repayment proposal (ADR-0049 §3.2).

    ``confirmed_amount_cents`` is the home amount actually accepted; ``None``
    confirms the full proposed amount. A partial confirm (``< proposed``) commits
    a partial ``Repayment`` and latches the proposal ``partially_confirmed``.
    Confirm is fold-changing, so ``expected_row_version`` is the §2.1 stale-intent
    token + §3.6 fingerprint component (REQUIRED).
    """

    model_config = ConfigDict(extra="forbid")

    confirmed_amount_cents: int | None = Field(default=None, gt=0)
    expected_row_version: int


class MemberRepaymentProposalRejectRequest(BaseModel):
    """Creditor rejects a member repayment proposal (ADR-0049 §3.2).

    Rejecting does not change the fold (no repayment is committed), so there is
    no ``expected_row_version``.
    """

    model_config = ConfigDict(extra="forbid")


class MemberRepaymentProposalWithdrawRequest(BaseModel):
    """Debtor withdraws their own pending proposal (ADR-0049 §3.2).

    A no-op body: withdraw targets the proposal by path id and only succeeds
    while it is still ``pending``. It does not change the fold.
    """

    model_config = ConfigDict(extra="forbid")


class MemberRepaymentProposalResponse(BaseModel):
    public_id: str
    debt_public_id: str
    status: str
    proposed_amount_cents: int
    confirmed_amount_cents: int | None = None
    home_currency_code: str
    original_currency_code: str | None = None
    original_amount_minor: int | None = None
    paid_at: datetime
    note: str | None = None
    expires_at: datetime
    created_at: datetime
    resolved_at: datetime | None = None
    supersedes_proposal_public_id: str | None = None
    committed_repayment_public_id: str | None = None

    @field_serializer("paid_at", "expires_at", "created_at", "resolved_at")
    def serialize_proposal_datetime(self, value: datetime | None) -> str | None:
        return to_iso(value)


class MemberRepaymentProposalListResponse(BaseModel):
    items: list[MemberRepaymentProposalResponse]
