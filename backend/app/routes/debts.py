"""ADR-0049 Debt domain routes (slice 1: list / get / create; slice 2: facts).

Thin route layer (§1): parse + auth + delegate to ``debt_service`` + return a
schema. No business logic, no SQL, no raw-exception leakage.

- ``GET /api/debts`` — ledger-scoped list with derived ``remaining`` / ``paid``.
- ``GET /api/debts/payables`` — viewer-personal payables in the selected ledger.
- ``GET /api/debts/receivables`` — viewer-personal local + cross-ledger receivables.
- ``GET /api/debts/{public_id}`` — one Debt; 404 ``debt_not_found``.
- ``GET /api/debts/{public_id}/repayments`` — bounded canonical repayment +
  repayment-void facts for restart-safe history.
- ``POST /api/debts`` — create one external/manual Debt.
- ``POST /api/debts/{public_id}/repayments`` — record a committed repayment (§3.1).
- ``POST /api/debts/{public_id}/adjustments`` — record a signed adjustment (§3.3).
- ``POST /api/debts/{public_id}/repayment-voids`` — void one repayment (§3.4).
- ``POST /api/debts/{public_id}/void`` — void the whole Debt (§3.5).
- ``POST /api/debts/{public_id}/forgive`` — creditor forgives a member Debt's remaining
  (§3.7 / §4, slice 8e-3; member + creditor only, fold-changing → cleared not voided).
- ``POST /api/debts/{public_id}/repayment-proposals`` — debtor proposes "I paid" (§3.2).
- ``POST /api/debts/{public_id}/repayment-proposals/{proposal_public_id}/withdraw``
  — debtor withdraws their pending proposal (§3.2).
- ``POST /api/debts/{public_id}/repayment-proposals/{proposal_public_id}/confirm``
  — creditor confirms (full/partial), committing a repayment (§3.2, fold-changing).
- ``POST /api/debts/{public_id}/repayment-proposals/{proposal_public_id}/reject``
  — creditor rejects the proposal (§3.2).
- ``GET /api/debts/{public_id}/repayment-proposals`` — list a Debt's proposals.

All writes are writers-only (``get_current_writer_context`` → viewer 403,
§5/§11), carry an ``Idempotency-Key`` ([[0042]]), and take ``expected_row_version``
in the body (§3.6 fingerprint + §2.1 stale-intent fence). Each replies with the
fold-after ``DebtResponse`` so the client has the fresh ``row_version``.

Create uses the low-level [[0042]] helpers directly (no path id to re-serialise
from on a HIT — the recorded ``resource_id`` locates the Debt). The fact writes
have a path id (the Debt ``public_id``) so they use the high-level
``claim_idempotent_request`` handshake: a HIT re-serialises the Debt's canonical
current fold WITHOUT re-entering the §2.1 serialized section (no second parent
bump, no second fact insert — §2.1 "replay does not bump").
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.database import get_db
from app.schemas import (
    DebtAdjustmentCreateRequest,
    DebtCreateRequest,
    DebtForgiveCreateRequest,
    DebtKindSetRequest,
    DebtListResponse,
    DebtResponse,
    DebtVoidCreateRequest,
    MemberRepaymentProposalConfirmRequest,
    MemberRepaymentProposalCreateRequest,
    MemberRepaymentProposalListResponse,
    MemberRepaymentProposalRejectRequest,
    MemberRepaymentProposalResponse,
    MemberRepaymentProposalWithdrawRequest,
    RepaymentCreateRequest,
    RepaymentCreateResponse,
    RepaymentFactListResponse,
    RepaymentVoidCreateRequest,
)
from app.services.debt_command_service import (
    create_debt_idempotently,
    forgive_debt_idempotently,
    record_adjustment_idempotently,
    record_repayment_idempotently,
    set_debt_kind_idempotently,
    void_debt_idempotently,
    void_repayment_idempotently,
)
from app.services.debt_proposal_command_service import (
    confirm_repayment_proposal_idempotently,
    create_repayment_proposal_idempotently,
    reject_repayment_proposal_idempotently,
    withdraw_repayment_proposal_idempotently,
)
from app.services.debt_service import (
    get_participant_debt_response,
    list_debts,
    list_payables_for_account,
    list_receivables_for_account,
    list_repayment_facts,
    list_repayment_proposals,
)
from app.tenants import AuthContext

router = APIRouter(
    prefix="/api/debts",
    tags=["debts"],
)


@router.get("", response_model=DebtListResponse)
def get_debts(
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> DebtListResponse:
    # ADR-0049 §3.2: each member row carries the server-authoritative viewer_is_debtor
    # for the authenticated account, so the communal list row frames the relationship
    # from the viewer's side (a bill_split member Debt's owner may be a non-owner member
    # → owner-relative direction alone can't frame it). External rows stay None.
    return list_debts(db, tenant_id=auth.tenant_id, viewer_account_id=auth.account_id)


@router.get("/payables", response_model=DebtListResponse)
def get_debt_payables(
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> DebtListResponse:
    """Return obligations the authenticated account needs to repay."""
    # The service resolves owner-relative direction against the authenticated account:
    # owner/i_owe + member-counterparty/owed_to_me. Merely administering this ledger never
    # exposes another member's personal external or member obligations.
    return list_payables_for_account(
        db,
        tenant_id=auth.tenant_id,
        account_id=auth.account_id,
    )


@router.get("/receivables", response_model=DebtListResponse)
def get_debt_receivables(
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> DebtListResponse:
    """Return obligations owed to the authenticated account."""
    # Same-ledger owner/member-counterparty rows are combined with cross-ledger member
    # creditor discovery. The service de-duplicates by public_id and keeps cross-ledger
    # shells redacted (ledger_id=None, §5.2). Both fixed paths stay before "/{public_id}".
    return list_receivables_for_account(
        db,
        tenant_id=auth.tenant_id,
        account_id=auth.account_id,
    )


@router.get("/{public_id}", response_model=DebtResponse)
def get_debt_detail(
    public_id: str,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> DebtResponse:
    # ADR-0049 §5.2: a member Debt's two parties can live in different ledgers
    # (a bill_split Debt is owned by the receiver's ledger with the sender as the
    # cross-ledger creditor). Resolve by participant union so the creditor can read
    # the obligation they must confirm; a non-member participant gets the Debt
    # shell only (ledger id redacted), and a non-participant gets debt_not_found.
    return get_participant_debt_response(db, public_id=public_id, ledger_id=auth.tenant_id, account_id=auth.account_id)


@router.get(
    "/{public_id}/repayments",
    response_model=RepaymentFactListResponse,
)
def get_repayment_facts(
    public_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> RepaymentFactListResponse:
    """Return canonical repayment + repayment-void facts for one visible Debt."""
    return list_repayment_facts(
        db,
        tenant_id=auth.tenant_id,
        actor_account_id=auth.account_id,
        public_id=public_id,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=DebtResponse, status_code=201)
def post_debt(
    payload: DebtCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> DebtResponse:
    return create_debt_idempotently(
        db,
        tenant_id=auth.tenant_id,
        actor_account_id=auth.account_id,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/{public_id}/repayments",
    response_model=RepaymentCreateResponse,
    status_code=201,
)
def post_repayment(
    public_id: str,
    payload: RepaymentCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> RepaymentCreateResponse:
    return record_repayment_idempotently(
        db,
        tenant_id=auth.tenant_id,
        actor_account_id=auth.account_id,
        public_id=public_id,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post("/{public_id}/adjustments", response_model=DebtResponse, status_code=201)
def post_adjustment(
    public_id: str,
    payload: DebtAdjustmentCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> DebtResponse:
    return record_adjustment_idempotently(
        db,
        tenant_id=auth.tenant_id,
        actor_account_id=auth.account_id,
        public_id=public_id,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post("/{public_id}/repayment-voids", response_model=DebtResponse, status_code=201)
def post_repayment_void(
    public_id: str,
    payload: RepaymentVoidCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> DebtResponse:
    return void_repayment_idempotently(
        db,
        tenant_id=auth.tenant_id,
        actor_account_id=auth.account_id,
        public_id=public_id,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post("/{public_id}/void", response_model=DebtResponse, status_code=201)
def post_debt_void(
    public_id: str,
    payload: DebtVoidCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> DebtResponse:
    return void_debt_idempotently(
        db,
        tenant_id=auth.tenant_id,
        actor_account_id=auth.account_id,
        public_id=public_id,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post("/{public_id}/forgive", response_model=DebtResponse, status_code=201)
def post_debt_forgive(
    public_id: str,
    payload: DebtForgiveCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> DebtResponse:
    return forgive_debt_idempotently(
        db,
        tenant_id=auth.tenant_id,
        actor_account_id=auth.account_id,
        public_id=public_id,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post("/{public_id}/kind", response_model=DebtResponse)
def post_debt_kind(
    public_id: str,
    payload: DebtKindSetRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> DebtResponse:
    return set_debt_kind_idempotently(
        db,
        tenant_id=auth.tenant_id,
        actor_account_id=auth.account_id,
        public_id=public_id,
        payload=payload,
        idempotency_key=idempotency_key,
    )


# ── ADR-0049 slice 3: member repayment proposals (§3.2) ──────────────────────


@router.post(
    "/{public_id}/repayment-proposals",
    response_model=MemberRepaymentProposalResponse,
    status_code=201,
)
def post_repayment_proposal(
    public_id: str,
    payload: MemberRepaymentProposalCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> MemberRepaymentProposalResponse:
    return create_repayment_proposal_idempotently(
        db,
        tenant_id=auth.tenant_id,
        actor_account_id=auth.account_id,
        public_id=public_id,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/{public_id}/repayment-proposals/{proposal_public_id}/withdraw",
    response_model=MemberRepaymentProposalResponse,
    status_code=201,
)
def post_repayment_proposal_withdraw(
    public_id: str,
    proposal_public_id: str,
    payload: MemberRepaymentProposalWithdrawRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> MemberRepaymentProposalResponse:
    return withdraw_repayment_proposal_idempotently(
        db,
        tenant_id=auth.tenant_id,
        actor_account_id=auth.account_id,
        public_id=public_id,
        proposal_public_id=proposal_public_id,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/{public_id}/repayment-proposals/{proposal_public_id}/confirm",
    response_model=DebtResponse,
    status_code=201,
)
def post_repayment_proposal_confirm(
    public_id: str,
    proposal_public_id: str,
    payload: MemberRepaymentProposalConfirmRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> DebtResponse:
    return confirm_repayment_proposal_idempotently(
        db,
        tenant_id=auth.tenant_id,
        actor_account_id=auth.account_id,
        public_id=public_id,
        proposal_public_id=proposal_public_id,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/{public_id}/repayment-proposals/{proposal_public_id}/reject",
    response_model=MemberRepaymentProposalResponse,
    status_code=201,
)
def post_repayment_proposal_reject(
    public_id: str,
    proposal_public_id: str,
    payload: MemberRepaymentProposalRejectRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> MemberRepaymentProposalResponse:
    return reject_repayment_proposal_idempotently(
        db,
        tenant_id=auth.tenant_id,
        actor_account_id=auth.account_id,
        public_id=public_id,
        proposal_public_id=proposal_public_id,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.get(
    "/{public_id}/repayment-proposals",
    response_model=MemberRepaymentProposalListResponse,
)
def get_repayment_proposals(
    public_id: str,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> MemberRepaymentProposalListResponse:
    # §5.2 participant-scoped: the cross-ledger creditor must see the pending
    # proposal awaiting their confirmation.
    return list_repayment_proposals(db, tenant_id=auth.tenant_id, actor_account_id=auth.account_id, public_id=public_id)
