"""Idempotent commands for the member Debt repayment handshake.

JSON API and HTML adapters share these commands so retries, actor-scoped
fingerprints, proposal lifecycle guards, and fold-changing confirmations keep
one implementation.
"""

from __future__ import annotations

from hashlib import sha256

from sqlalchemy.orm import Session

from app.errors import AppError
from app.schemas import (
    DebtResponse,
    MemberRepaymentProposalConfirmRequest,
    MemberRepaymentProposalCreateRequest,
    MemberRepaymentProposalRejectRequest,
    MemberRepaymentProposalResponse,
    MemberRepaymentProposalWithdrawRequest,
)
from app.services.currency_common import normalize_currency_code
from app.services.debt_service import (
    confirm_repayment_proposal,
    create_repayment_proposal,
    get_participant_debt_response,
    get_repayment_proposal_response,
    reject_repayment_proposal,
    withdraw_repayment_proposal,
)
from app.services.exchange_rate_service import (
    amount_major_to_minor,
    default_rate_date,
)
from app.services.idempotency import (
    IdempotencyOutcomeKind,
    claim_idempotency_key,
    claim_idempotent_request,
    fingerprint_request,
    mark_idempotency_succeeded,
    reject_idempotency_target_mismatch,
)
from app.services.time_service import to_iso

_DEBT_TARGET_TYPE = "debt"
_PROPOSAL_TARGET_TYPE = "debt_repayment_proposal"
_PROPOSAL_CREATE_OPERATION = "debt.repayment_proposal.create"
_PROPOSAL_WITHDRAW_OPERATION = "debt.repayment_proposal.withdraw"
_PROPOSAL_CONFIRM_OPERATION = "debt.repayment_proposal.confirm"
_PROPOSAL_REJECT_OPERATION = "debt.repayment_proposal.reject"


def _proposal_target_id(public_id: str, proposal_public_id: str) -> str:
    """Fit the parent/proposal tuple into the shared idempotency target column."""
    return sha256(f"{public_id}:{proposal_public_id}".encode()).hexdigest()


def _actor_scoped_body(
    body: dict[str, object],
    *,
    actor_account_id: int,
) -> dict[str, object]:
    return {**body, "actor_account_id": actor_account_id}


def _create_fingerprint_body(
    payload: MemberRepaymentProposalCreateRequest,
) -> dict[str, object]:
    body = {
        key: value for key, value in payload.model_dump(mode="json", exclude_unset=True).items() if value is not None
    }
    if payload.note is not None:
        note = payload.note.strip()
        if note:
            body["note"] = note
        else:
            body.pop("note", None)
    if payload.paid_at is not None:
        body["paid_at"] = to_iso(payload.paid_at)
        body["paid_at_rate_date"] = default_rate_date(payload.paid_at).isoformat()
    if payload.expires_at is not None:
        body["expires_at"] = to_iso(payload.expires_at)
    if payload.original_currency_code is not None:
        body["original_currency_code"] = payload.original_currency_code.strip().upper()
    if payload.original_amount is not None:
        body["original_amount"] = amount_major_to_minor(
            payload.original_amount,
            normalize_currency_code(payload.original_currency_code),
        )
    return body


def _confirm_fingerprint_body(
    payload: MemberRepaymentProposalConfirmRequest,
    *,
    proposed_amount_cents: int,
) -> dict[str, object]:
    body = payload.model_dump(
        mode="json",
        exclude_unset=True,
        exclude={"expected_row_version"},
    )
    if payload.confirmed_amount_cents is None or payload.confirmed_amount_cents == proposed_amount_cents:
        body.pop("confirmed_amount_cents", None)
    return body


def create_repayment_proposal_idempotently(
    db: Session,
    *,
    tenant_id: str,
    actor_account_id: int,
    public_id: str,
    payload: MemberRepaymentProposalCreateRequest,
    idempotency_key: str | None,
) -> MemberRepaymentProposalResponse:
    """Create a member repayment proposal with canonical replay rules."""
    if not idempotency_key:
        raise AppError("idempotency_key_required", status_code=422)
    fingerprint = fingerprint_request(
        operation=_PROPOSAL_CREATE_OPERATION,
        target_id=public_id,
        body=_actor_scoped_body(
            _create_fingerprint_body(payload),
            actor_account_id=actor_account_id,
        ),
        expected_row_version=None,
    )
    outcome = claim_idempotency_key(
        db,
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
        operation=_PROPOSAL_CREATE_OPERATION,
        request_fingerprint=fingerprint,
        target_type=_PROPOSAL_TARGET_TYPE,
        target_id=public_id,
    )
    if outcome.kind is IdempotencyOutcomeKind.HIT:
        return get_repayment_proposal_response(
            db,
            tenant_id=tenant_id,
            actor_account_id=actor_account_id,
            public_id=public_id,
            proposal_public_id=outcome.row.resource_id,
        )
    if outcome.kind is IdempotencyOutcomeKind.IN_PROGRESS:
        raise AppError("idempotency_key_in_progress", status_code=409)
    if outcome.kind is IdempotencyOutcomeKind.FINGERPRINT_MISMATCH:
        raise AppError("idempotency_key_reused", status_code=422)

    response = create_repayment_proposal(
        db,
        tenant_id=tenant_id,
        actor_account_id=actor_account_id,
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


def withdraw_repayment_proposal_idempotently(
    db: Session,
    *,
    tenant_id: str,
    actor_account_id: int,
    public_id: str,
    proposal_public_id: str,
    payload: MemberRepaymentProposalWithdrawRequest,
    idempotency_key: str | None,
) -> MemberRepaymentProposalResponse:
    """Withdraw a pending proposal without changing the parent Debt fold."""
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=tenant_id,
        operation=_PROPOSAL_WITHDRAW_OPERATION,
        target_id=_proposal_target_id(public_id, proposal_public_id),
        target_type=_PROPOSAL_TARGET_TYPE,
        body=_actor_scoped_body(
            payload.model_dump(mode="json", exclude_unset=True),
            actor_account_id=actor_account_id,
        ),
        expected_row_version=None,
    )
    if claim is None:
        return get_repayment_proposal_response(
            db,
            tenant_id=tenant_id,
            actor_account_id=actor_account_id,
            public_id=public_id,
            proposal_public_id=proposal_public_id,
        )
    response = withdraw_repayment_proposal(
        db,
        tenant_id=tenant_id,
        actor_account_id=actor_account_id,
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


def confirm_repayment_proposal_idempotently(
    db: Session,
    *,
    tenant_id: str,
    actor_account_id: int,
    public_id: str,
    proposal_public_id: str,
    payload: MemberRepaymentProposalConfirmRequest,
    idempotency_key: str | None,
) -> DebtResponse:
    """Confirm all or part of a proposal and return the participant fold."""
    if not idempotency_key:
        raise AppError("idempotency_key_required", status_code=422)
    target_id = _proposal_target_id(public_id, proposal_public_id)
    reject_idempotency_target_mismatch(
        db,
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
        operation=_PROPOSAL_CONFIRM_OPERATION,
        target_id=target_id,
        target_type=_PROPOSAL_TARGET_TYPE,
    )
    proposal = get_repayment_proposal_response(
        db,
        tenant_id=tenant_id,
        actor_account_id=actor_account_id,
        public_id=public_id,
        proposal_public_id=proposal_public_id,
    )
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=tenant_id,
        operation=_PROPOSAL_CONFIRM_OPERATION,
        target_id=target_id,
        target_type=_PROPOSAL_TARGET_TYPE,
        body=_actor_scoped_body(
            _confirm_fingerprint_body(
                payload,
                proposed_amount_cents=proposal.proposed_amount_cents,
            ),
            actor_account_id=actor_account_id,
        ),
        expected_row_version=payload.expected_row_version,
    )
    if claim is None:
        return get_participant_debt_response(
            db,
            public_id=public_id,
            ledger_id=tenant_id,
            account_id=actor_account_id,
        )
    confirm_repayment_proposal(
        db,
        tenant_id=tenant_id,
        actor_account_id=actor_account_id,
        public_id=public_id,
        proposal_public_id=proposal_public_id,
        payload=payload,
        idempotency_key=idempotency_key,
        commit=False,
    )
    mark_idempotency_succeeded(
        db,
        claim,
        resource_type=_DEBT_TARGET_TYPE,
        resource_id=public_id,
    )
    db.commit()
    db.expire_all()
    return get_participant_debt_response(
        db,
        public_id=public_id,
        ledger_id=tenant_id,
        account_id=actor_account_id,
    )


def reject_repayment_proposal_idempotently(
    db: Session,
    *,
    tenant_id: str,
    actor_account_id: int,
    public_id: str,
    proposal_public_id: str,
    payload: MemberRepaymentProposalRejectRequest,
    idempotency_key: str | None,
) -> MemberRepaymentProposalResponse:
    """Reject a pending proposal without changing the parent Debt fold."""
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=tenant_id,
        operation=_PROPOSAL_REJECT_OPERATION,
        target_id=_proposal_target_id(public_id, proposal_public_id),
        target_type=_PROPOSAL_TARGET_TYPE,
        body=_actor_scoped_body(
            payload.model_dump(mode="json", exclude_unset=True),
            actor_account_id=actor_account_id,
        ),
        expected_row_version=None,
    )
    if claim is None:
        return get_repayment_proposal_response(
            db,
            tenant_id=tenant_id,
            actor_account_id=actor_account_id,
            public_id=public_id,
            proposal_public_id=proposal_public_id,
        )
    response = reject_repayment_proposal(
        db,
        tenant_id=tenant_id,
        actor_account_id=actor_account_id,
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
