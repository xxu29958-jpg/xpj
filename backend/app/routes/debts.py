"""ADR-0049 Debt domain routes (slice 1: list / get / create; slice 2: facts).

Thin route layer (§1): parse + auth + delegate to ``debt_service`` + return a
schema. No business logic, no SQL, no raw-exception leakage.

- ``GET /api/debts`` — ledger-scoped list with derived ``remaining`` / ``paid``.
- ``GET /api/debts/{public_id}`` — one Debt; 404 ``debt_not_found``.
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

from hashlib import sha256

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.database import get_db
from app.errors import AppError
from app.schemas import (
    DebtAdjustmentCreateRequest,
    DebtCreateRequest,
    DebtForgiveCreateRequest,
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
    RepaymentVoidCreateRequest,
)
from app.services.currency_common import normalize_currency_code
from app.services.debt_service import (
    confirm_repayment_proposal,
    create_debt,
    create_repayment_proposal,
    forgive_debt,
    get_debt_response,
    get_participant_debt_response,
    get_repayment_proposal_response,
    get_repayment_public_id_for_idempotency,
    list_debts,
    list_repayment_proposals,
    record_adjustment,
    record_repayment,
    reject_repayment_proposal,
    void_debt,
    void_repayment,
    withdraw_repayment_proposal,
)
from app.services.exchange_rate_service import amount_major_to_minor, default_rate_date
from app.services.idempotency import (
    IdempotencyOutcomeKind,
    claim_idempotency_key,
    claim_idempotent_request,
    fingerprint_request,
    mark_idempotency_succeeded,
    reject_idempotency_target_mismatch,
)
from app.services.time_service import to_iso
from app.tenants import AuthContext

router = APIRouter(
    prefix="/api/debts",
    tags=["debts"],
)

_CREATE_OPERATION = "create_debt"
_DEBT_TARGET_TYPE = "debt"
_REPAYMENT_OPERATION = "record_repayment"
_ADJUSTMENT_OPERATION = "record_adjustment"
_REPAYMENT_VOID_OPERATION = "void_repayment"
_DEBT_VOID_OPERATION = "void_debt"
# ADR-0049 §3.7 / §4 (slice 8e-3): creditor forgiveness of a member Debt's remaining.
_DEBT_FORGIVE_OPERATION = "forgive_debt"
# ADR-0049 slice 3: member repayment proposal (§3.2). Create anchors on the
# parent Debt public_id; proposal-targeted ops also include the parent Debt so a
# cross-debt path replay cannot HIT on the proposal id alone.
_PROPOSAL_TARGET_TYPE = "debt_repayment_proposal"
_PROPOSAL_CREATE_OPERATION = "debt.repayment_proposal.create"
_PROPOSAL_WITHDRAW_OPERATION = "debt.repayment_proposal.withdraw"
_PROPOSAL_CONFIRM_OPERATION = "debt.repayment_proposal.confirm"
_PROPOSAL_REJECT_OPERATION = "debt.repayment_proposal.reject"


def _proposal_target_id(public_id: str, proposal_public_id: str) -> str:
    # api_idempotency_keys.target_id is VARCHAR(64); hash the parent+proposal
    # tuple so both ids shape the fingerprint without widening the shared table.
    return sha256(f"{public_id}:{proposal_public_id}".encode()).hexdigest()


def _actor_scoped_fingerprint_body(
    body: dict[str, object], *, actor_account_id: int
) -> dict[str, object]:
    # ADR-0049 §3.6 scopes Debt idempotency fingerprints by actor. This matters
    # because a HIT returns before debtor/creditor service guards re-run.
    return {**body, "actor_account_id": actor_account_id}


def _proposal_create_fingerprint_body(
    payload: MemberRepaymentProposalCreateRequest,
) -> dict[str, object]:
    body = {
        key: value
        for key, value in payload.model_dump(mode="json", exclude_unset=True).items()
        if value is not None
    }
    if payload.note is not None:
        note = payload.note.strip()
        if note:
            body["note"] = note
        else:
            body.pop("note", None)
    if payload.paid_at is not None:
        body["paid_at"] = to_iso(payload.paid_at)
        # ``to_iso`` canonicalizes equal instants, but FX freeze preserves
        # offset/naive rate-date semantics via default_rate_date(). Include that
        # date so a replay that would freeze a different home amount cannot HIT.
        body["paid_at_rate_date"] = default_rate_date(payload.paid_at).isoformat()
    if payload.expires_at is not None:
        body["expires_at"] = to_iso(payload.expires_at)
    if payload.original_currency_code is not None:
        body["original_currency_code"] = payload.original_currency_code.strip().upper()
    if payload.original_amount is not None:
        # §3.6: hash the *stored* minor-unit amount (currency-aware HALF_UP
        # rounding, mirroring _freeze_foreign_amount's
        # amount_major_to_minor(normalize_currency_code(...))), not the raw
        # major-unit Decimal. Otherwise a lost-response retry whose serializer
        # emits a finer decimal (e.g. USD "10.004" vs "10.00", both → stored
        # original_amount_minor 1000) would differ in the fingerprint and
        # falsely return idempotency_key_reused instead of the canonical HIT.
        body["original_amount"] = amount_major_to_minor(
            payload.original_amount, normalize_currency_code(payload.original_currency_code)
        )
    return body


def _proposal_confirm_fingerprint_body(
    payload: MemberRepaymentProposalConfirmRequest, *, proposed_amount_cents: int
) -> dict[str, object]:
    body = payload.model_dump(
        mode="json", exclude_unset=True, exclude={"expected_row_version"}
    )
    if (
        payload.confirmed_amount_cents is None
        or payload.confirmed_amount_cents == proposed_amount_cents
    ):
        body.pop("confirmed_amount_cents", None)
    return body


def _repayment_create_response(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    repayment_public_id: str,
) -> RepaymentCreateResponse:
    debt = get_debt_response(db, tenant_id=tenant_id, public_id=public_id)
    return RepaymentCreateResponse(
        **debt.model_dump(),
        repayment_public_id=repayment_public_id,
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
    return get_participant_debt_response(
        db, public_id=public_id, ledger_id=auth.tenant_id, account_id=auth.account_id
    )


@router.post("", response_model=DebtResponse, status_code=201)
def post_debt(
    payload: DebtCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> DebtResponse:
    # ADR-0042: claim the Idempotency-Key BEFORE creating the row so an
    # offline-outbox replay of a committed-but-unseen create returns the SAME
    # Debt instead of inserting a second one. A create has no path id, so the
    # key itself anchors the fingerprint (per operation+key+body) and the
    # recorded ``resource_id`` locates the Debt on a HIT.
    if not idempotency_key:
        raise AppError("idempotency_key_required", status_code=422)
    fingerprint = fingerprint_request(
        operation=_CREATE_OPERATION,
        target_id=idempotency_key,
        body=_actor_scoped_fingerprint_body(
            payload.model_dump(mode="json", exclude_unset=True),
            actor_account_id=auth.account_id,
        ),
        expected_row_version=None,
    )
    outcome = claim_idempotency_key(
        db,
        tenant_id=auth.tenant_id,
        idempotency_key=idempotency_key,
        operation=_CREATE_OPERATION,
        request_fingerprint=fingerprint,
        target_type=_DEBT_TARGET_TYPE,
        target_id=idempotency_key,
    )
    if outcome.kind is IdempotencyOutcomeKind.HIT:  # §4.6 — re-serialise the created Debt
        return get_debt_response(
            db, tenant_id=auth.tenant_id, public_id=outcome.row.resource_id
        )
    if outcome.kind is IdempotencyOutcomeKind.IN_PROGRESS:
        raise AppError("idempotency_key_in_progress", status_code=409)
    if outcome.kind is IdempotencyOutcomeKind.FINGERPRINT_MISMATCH:
        raise AppError("idempotency_key_reused", status_code=422)

    debt = create_debt(
        db,
        tenant_id=auth.tenant_id,
        created_by_account_id=auth.account_id,
        owner_account_id=auth.account_id,
        payload=payload,
        commit=False,
    )
    mark_idempotency_succeeded(
        db, outcome.row, resource_type=_DEBT_TARGET_TYPE, resource_id=debt.public_id
    )
    db.commit()
    return get_debt_response(db, tenant_id=auth.tenant_id, public_id=debt.public_id)


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
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=auth.tenant_id,
        operation=_REPAYMENT_OPERATION,
        target_id=public_id,
        target_type=_DEBT_TARGET_TYPE,
        body=_actor_scoped_fingerprint_body(
            payload.model_dump(
                mode="json", exclude_unset=True, exclude={"expected_row_version"}
            ),
            actor_account_id=auth.account_id,
        ),
        expected_row_version=payload.expected_row_version,
    )
    if claim is None:  # §2.1 replay: re-serialise the fold, do NOT bump again.
        repayment_public_id = get_repayment_public_id_for_idempotency(
            db,
            tenant_id=auth.tenant_id,
            public_id=public_id,
            idempotency_key=idempotency_key,
        )
        return _repayment_create_response(
            db,
            tenant_id=auth.tenant_id,
            public_id=public_id,
            repayment_public_id=repayment_public_id,
        )
    result = record_repayment(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        actor_account_id=auth.account_id,
        payload=payload,
        idempotency_key=idempotency_key,
        commit=False,
    )
    mark_idempotency_succeeded(
        db, claim, resource_type="repayment", resource_id=result.repayment_public_id
    )
    db.commit()
    # bump_row_version emits a SQL ``row_version + 1`` expression; with
    # ``expire_on_commit=False`` the in-session Debt still holds that expression,
    # so expire before re-reading the fold for the response (mirrors
    # goal_service.update_goal's post-CAS expire_all).
    db.expire_all()
    return _repayment_create_response(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        repayment_public_id=result.repayment_public_id,
    )


@router.post("/{public_id}/adjustments", response_model=DebtResponse, status_code=201)
def post_adjustment(
    public_id: str,
    payload: DebtAdjustmentCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> DebtResponse:
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=auth.tenant_id,
        operation=_ADJUSTMENT_OPERATION,
        target_id=public_id,
        target_type=_DEBT_TARGET_TYPE,
        body=_actor_scoped_fingerprint_body(
            payload.model_dump(
                mode="json", exclude_unset=True, exclude={"expected_row_version"}
            ),
            actor_account_id=auth.account_id,
        ),
        expected_row_version=payload.expected_row_version,
    )
    if claim is None:
        return get_debt_response(db, tenant_id=auth.tenant_id, public_id=public_id)
    debt = record_adjustment(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        actor_account_id=auth.account_id,
        payload=payload,
        idempotency_key=idempotency_key,
        commit=False,
    )
    mark_idempotency_succeeded(
        db, claim, resource_type=_DEBT_TARGET_TYPE, resource_id=debt.public_id
    )
    db.commit()
    # bump_row_version emits a SQL ``row_version + 1`` expression; with
    # ``expire_on_commit=False`` the in-session Debt still holds that expression,
    # so expire before re-reading the fold for the response (mirrors
    # goal_service.update_goal's post-CAS expire_all).
    db.expire_all()
    return get_debt_response(db, tenant_id=auth.tenant_id, public_id=public_id)


@router.post(
    "/{public_id}/repayment-voids", response_model=DebtResponse, status_code=201
)
def post_repayment_void(
    public_id: str,
    payload: RepaymentVoidCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> DebtResponse:
    # The §2.1 serialization anchor is the parent Debt ``public_id``; the target
    # repayment id rides in the body + fingerprint.
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=auth.tenant_id,
        operation=_REPAYMENT_VOID_OPERATION,
        target_id=public_id,
        target_type=_DEBT_TARGET_TYPE,
        body=_actor_scoped_fingerprint_body(
            payload.model_dump(
                mode="json", exclude_unset=True, exclude={"expected_row_version"}
            ),
            actor_account_id=auth.account_id,
        ),
        expected_row_version=payload.expected_row_version,
    )
    if claim is None:
        return get_debt_response(db, tenant_id=auth.tenant_id, public_id=public_id)
    debt = void_repayment(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        payload=payload,
        actor_account_id=auth.account_id,
        idempotency_key=idempotency_key,
        commit=False,
    )
    mark_idempotency_succeeded(
        db, claim, resource_type=_DEBT_TARGET_TYPE, resource_id=debt.public_id
    )
    db.commit()
    # bump_row_version emits a SQL ``row_version + 1`` expression; with
    # ``expire_on_commit=False`` the in-session Debt still holds that expression,
    # so expire before re-reading the fold for the response (mirrors
    # goal_service.update_goal's post-CAS expire_all).
    db.expire_all()
    return get_debt_response(db, tenant_id=auth.tenant_id, public_id=public_id)


@router.post("/{public_id}/void", response_model=DebtResponse, status_code=201)
def post_debt_void(
    public_id: str,
    payload: DebtVoidCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> DebtResponse:
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=auth.tenant_id,
        operation=_DEBT_VOID_OPERATION,
        target_id=public_id,
        target_type=_DEBT_TARGET_TYPE,
        body=_actor_scoped_fingerprint_body(
            payload.model_dump(
                mode="json", exclude_unset=True, exclude={"expected_row_version"}
            ),
            actor_account_id=auth.account_id,
        ),
        expected_row_version=payload.expected_row_version,
    )
    if claim is None:
        return get_debt_response(db, tenant_id=auth.tenant_id, public_id=public_id)
    debt = void_debt(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        payload=payload,
        actor_account_id=auth.account_id,
        idempotency_key=idempotency_key,
        commit=False,
    )
    mark_idempotency_succeeded(
        db, claim, resource_type=_DEBT_TARGET_TYPE, resource_id=debt.public_id
    )
    db.commit()
    # bump_row_version emits a SQL ``row_version + 1`` expression; with
    # ``expire_on_commit=False`` the in-session Debt still holds that expression,
    # so expire before re-reading the fold for the response (mirrors
    # goal_service.update_goal's post-CAS expire_all).
    db.expire_all()
    return get_debt_response(db, tenant_id=auth.tenant_id, public_id=public_id)


@router.post("/{public_id}/forgive", response_model=DebtResponse, status_code=201)
def post_debt_forgive(
    public_id: str,
    payload: DebtForgiveCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> DebtResponse:
    # ADR-0049 §3.7 / §4: creditor waiver of a member Debt's remaining ("算了，不用还了").
    # Member-Debt + creditor only; one-sided (no debtor confirmation). Fold-changing → it
    # carries expected_row_version (§2.1 fence + §3.6 fingerprint); the member + creditor
    # guards run INSIDE forgive_debt after the claim — the actor-scoped fingerprint stops a
    # different actor's replay from HITting past those guards. §5.2: the creditor may be in
    # ANOTHER ledger, so the HIT replay + success both re-serialise via
    # ``get_participant_debt_response`` (mirrors post_repayment_proposal_confirm, NOT
    # post_debt_void's ledger-scoped get_debt_response).
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=auth.tenant_id,
        operation=_DEBT_FORGIVE_OPERATION,
        target_id=public_id,
        target_type=_DEBT_TARGET_TYPE,
        body=_actor_scoped_fingerprint_body(
            payload.model_dump(
                mode="json", exclude_unset=True, exclude={"expected_row_version"}
            ),
            actor_account_id=auth.account_id,
        ),
        expected_row_version=payload.expected_row_version,
    )
    if claim is None:  # §2.1 replay: re-serialise the fold, do NOT bump again.
        return get_participant_debt_response(
            db, public_id=public_id, ledger_id=auth.tenant_id, account_id=auth.account_id
        )
    forgive_debt(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        actor_account_id=auth.account_id,
        expected_row_version=payload.expected_row_version,
        idempotency_key=idempotency_key,
        commit=False,
    )
    mark_idempotency_succeeded(
        db, claim, resource_type=_DEBT_TARGET_TYPE, resource_id=public_id
    )
    db.commit()
    # bump_row_version leaves a SQL ``row_version + 1`` expression on the in-session Debt;
    # expire before re-reading the fold for the response (mirrors the slice-2 fact routes).
    db.expire_all()
    # §5.2: a cross-ledger creditor gets the Debt shell (ledger id redacted).
    return get_participant_debt_response(
        db, public_id=public_id, ledger_id=auth.tenant_id, account_id=auth.account_id
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
    # Create has no proposal id yet, so — like ``post_debt`` — it uses the
    # low-level [[0042]] helpers directly; the recorded ``resource_id`` (the new
    # proposal public_id) locates the proposal on a HIT. The fingerprint target is
    # the PARENT debt ``public_id`` (§3.6: the narrowest available target), so the
    # same key + same body against a DIFFERENT debt is ``idempotency_key_reused``,
    # not a cross-debt HIT that would serialise debt A's proposal under debt B.
    # Creating a proposal is NOT fold-changing, so there is no
    # ``expected_row_version`` (the parent CAS happens only on confirm).
    if not idempotency_key:
        raise AppError("idempotency_key_required", status_code=422)
    fingerprint = fingerprint_request(
        operation=_PROPOSAL_CREATE_OPERATION,
        target_id=public_id,
        body=_actor_scoped_fingerprint_body(
            _proposal_create_fingerprint_body(payload),
            actor_account_id=auth.account_id,
        ),
        expected_row_version=None,
    )
    outcome = claim_idempotency_key(
        db,
        tenant_id=auth.tenant_id,
        idempotency_key=idempotency_key,
        operation=_PROPOSAL_CREATE_OPERATION,
        request_fingerprint=fingerprint,
        target_type=_PROPOSAL_TARGET_TYPE,
        target_id=public_id,
    )
    if outcome.kind is IdempotencyOutcomeKind.HIT:  # §4.6 — re-serialise the proposal
        return get_repayment_proposal_response(
            db,
            tenant_id=auth.tenant_id,
            actor_account_id=auth.account_id,
            public_id=public_id,
            proposal_public_id=outcome.row.resource_id,
        )
    if outcome.kind is IdempotencyOutcomeKind.IN_PROGRESS:
        raise AppError("idempotency_key_in_progress", status_code=409)
    if outcome.kind is IdempotencyOutcomeKind.FINGERPRINT_MISMATCH:
        raise AppError("idempotency_key_reused", status_code=422)

    response = create_repayment_proposal(
        db,
        tenant_id=auth.tenant_id,
        actor_account_id=auth.account_id,
        public_id=public_id,
        payload=payload,
        idempotency_key=idempotency_key,
        commit=False,
    )
    mark_idempotency_succeeded(
        db,
        outcome.row,
        resource_type=_PROPOSAL_TARGET_TYPE,
        resource_id=response.public_id,
    )
    db.commit()
    return response


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
    # Proposal-targeted op: anchor the [[0042]] fingerprint on the parent+proposal pair.
    # Withdraw is NOT fold-changing, so ``expected_row_version`` is None.
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=auth.tenant_id,
        operation=_PROPOSAL_WITHDRAW_OPERATION,
        target_id=_proposal_target_id(public_id, proposal_public_id),
        target_type=_PROPOSAL_TARGET_TYPE,
        body=_actor_scoped_fingerprint_body(
            payload.model_dump(mode="json", exclude_unset=True),
            actor_account_id=auth.account_id,
        ),
        expected_row_version=None,
    )
    if claim is None:  # replay: re-serialise the proposal's canonical state.
        return get_repayment_proposal_response(
            db,
            tenant_id=auth.tenant_id,
            actor_account_id=auth.account_id,
            public_id=public_id,
            proposal_public_id=proposal_public_id,
        )
    response = withdraw_repayment_proposal(
        db,
        tenant_id=auth.tenant_id,
        actor_account_id=auth.account_id,
        public_id=public_id,
        proposal_public_id=proposal_public_id,
        idempotency_key=idempotency_key,
        commit=False,
    )
    mark_idempotency_succeeded(
        db,
        claim,
        resource_type=_PROPOSAL_TARGET_TYPE,
        resource_id=response.public_id,
    )
    db.commit()
    return response


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
    if not idempotency_key:
        raise AppError("idempotency_key_required", status_code=422)
    target_id = _proposal_target_id(public_id, proposal_public_id)
    reject_idempotency_target_mismatch(
        db,
        tenant_id=auth.tenant_id,
        idempotency_key=idempotency_key,
        operation=_PROPOSAL_CONFIRM_OPERATION,
        target_id=target_id,
        target_type=_PROPOSAL_TARGET_TYPE,
    )
    proposal = get_repayment_proposal_response(
        db,
        tenant_id=auth.tenant_id,
        actor_account_id=auth.account_id,
        public_id=public_id,
        proposal_public_id=proposal_public_id,
    )
    # Confirm commits a Repayment → fold-changing, so it carries
    # ``expected_row_version`` (§2.1 stale-intent fence + §3.6 fingerprint) and
    # replies with the fold-after DebtResponse. A HIT re-serialises the Debt
    # WITHOUT re-entering the §2.1 serialized section (no second bump / repayment).
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=auth.tenant_id,
        operation=_PROPOSAL_CONFIRM_OPERATION,
        target_id=target_id,
        target_type=_PROPOSAL_TARGET_TYPE,
        body=_actor_scoped_fingerprint_body(
            _proposal_confirm_fingerprint_body(
                payload, proposed_amount_cents=proposal.proposed_amount_cents
            ),
            actor_account_id=auth.account_id,
        ),
        expected_row_version=payload.expected_row_version,
    )
    if claim is None:  # §2.1 replay: re-serialise the fold, do NOT bump again.
        # §5.2: participant-scoped + shell-redacted for a cross-ledger creditor.
        return get_participant_debt_response(
            db, public_id=public_id, ledger_id=auth.tenant_id, account_id=auth.account_id
        )
    confirm_repayment_proposal(
        db,
        tenant_id=auth.tenant_id,
        actor_account_id=auth.account_id,
        public_id=public_id,
        proposal_public_id=proposal_public_id,
        payload=payload,
        idempotency_key=idempotency_key,
        commit=False,
    )
    mark_idempotency_succeeded(
        db, claim, resource_type=_DEBT_TARGET_TYPE, resource_id=public_id
    )
    db.commit()
    # bump_row_version emits a SQL ``row_version + 1`` expression; expire before
    # re-reading the fold for the response (mirrors the slice-2 fact routes).
    db.expire_all()
    # §5.2: a cross-ledger creditor gets the Debt shell (ledger id redacted).
    return get_participant_debt_response(
        db, public_id=public_id, ledger_id=auth.tenant_id, account_id=auth.account_id
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
    # Reject is NOT fold-changing (no repayment committed), so no
    # ``expected_row_version``.
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=auth.tenant_id,
        operation=_PROPOSAL_REJECT_OPERATION,
        target_id=_proposal_target_id(public_id, proposal_public_id),
        target_type=_PROPOSAL_TARGET_TYPE,
        body=_actor_scoped_fingerprint_body(
            payload.model_dump(mode="json", exclude_unset=True),
            actor_account_id=auth.account_id,
        ),
        expected_row_version=None,
    )
    if claim is None:  # replay: re-serialise the proposal's canonical state.
        return get_repayment_proposal_response(
            db,
            tenant_id=auth.tenant_id,
            actor_account_id=auth.account_id,
            public_id=public_id,
            proposal_public_id=proposal_public_id,
        )
    response = reject_repayment_proposal(
        db,
        tenant_id=auth.tenant_id,
        actor_account_id=auth.account_id,
        public_id=public_id,
        proposal_public_id=proposal_public_id,
        payload=payload,
        idempotency_key=idempotency_key,
        commit=False,
    )
    mark_idempotency_succeeded(
        db,
        claim,
        resource_type=_PROPOSAL_TARGET_TYPE,
        resource_id=response.public_id,
    )
    db.commit()
    return response


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
    return list_repayment_proposals(
        db, tenant_id=auth.tenant_id, actor_account_id=auth.account_id, public_id=public_id
    )
