"""One transaction and original accepted receipt for both split-change clients."""

from collections.abc import Callable
from typing import Literal, TypeVar

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.errors import AppError
from app.schemas._bill_split_change import (
    BillSplitAgreementResponse,
    BillSplitChangeAcceptRequest,
    BillSplitChangeCreateRequest,
    BillSplitChangeProposalResponse,
)
from app.services.bill_split_service._agreement_commands import (
    accept_bill_split_change,
    create_bill_split_change,
    resolve_bill_split_change,
)
from app.services.bill_split_service._agreement_context import agreement_context, require_agreement_party
from app.services.bill_split_service._agreement_queries import get_bill_split_agreement, get_bill_split_change_proposal
from app.services.idempotency import (
    IdempotencyOutcomeKind,
    claim_idempotency_key,
    fingerprint_request,
    mark_idempotency_succeeded,
)

ResponseT = TypeVar("ResponseT", BillSplitAgreementResponse, BillSplitChangeProposalResponse)


def _execute(
    db: Session, *, tenant_id: str, actor_account_id: int, public_id: str,
    operation: str, idempotency_key: str | None, payload: BaseModel | None,
    proposal_public_id: str | None, response_type: type[ResponseT], mutate: Callable[[], ResponseT],
) -> ResponseT:
    if not idempotency_key:
        raise AppError("idempotency_key_required", status_code=422)
    if len(idempotency_key) > 64:
        raise AppError("invalid_request", status_code=422)
    try:
        # Recheck current visibility before releasing even a historical receipt.
        context = agreement_context(db, tenant_id=tenant_id, actor_account_id=actor_account_id, public_id=public_id)
        require_agreement_party(context, actor_account_id)
        body = {"actor_account_id": actor_account_id, "proposal_public_id": proposal_public_id,
            "payload": payload.model_dump(mode="json") if payload is not None else {}}
        claim = claim_idempotency_key(db, tenant_id=tenant_id, idempotency_key=idempotency_key,
            operation=operation, target_type="bill_split_change", target_id=public_id,
            request_fingerprint=fingerprint_request(operation=operation, target_id=public_id,
                body=body, expected_row_version=None))
        if claim.kind is IdempotencyOutcomeKind.FINGERPRINT_MISMATCH:
            raise AppError("idempotency_key_reused", status_code=422)
        if claim.kind is IdempotencyOutcomeKind.IN_PROGRESS:
            raise AppError("idempotency_key_in_progress", status_code=409)
        if claim.kind is IdempotencyOutcomeKind.HIT:
            return response_type.model_validate(claim.row.response_body)
        result = mutate()
        mark_idempotency_succeeded(db, claim.row, resource_type="debt",
            resource_id=context.original.public_id,
            response_body=result.model_dump(mode="json"))
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def create_bill_split_change_idempotently(
    db: Session, *, tenant_id: str, actor_account_id: int, public_id: str,
    payload: BillSplitChangeCreateRequest, idempotency_key: str | None,
) -> BillSplitChangeProposalResponse:
    def mutate() -> BillSplitChangeProposalResponse:
        proposal = create_bill_split_change(db, tenant_id=tenant_id, actor_account_id=actor_account_id,
            public_id=public_id, payload=payload)
        return get_bill_split_change_proposal(db, tenant_id=tenant_id, actor_account_id=actor_account_id,
            public_id=public_id, proposal_public_id=proposal.public_id)

    return _execute(db, tenant_id=tenant_id, actor_account_id=actor_account_id, public_id=public_id,
        operation="create_bill_split_change_proposal", idempotency_key=idempotency_key, payload=payload,
        proposal_public_id=None, response_type=BillSplitChangeProposalResponse, mutate=mutate)


def accept_bill_split_change_idempotently(
    db: Session, *, tenant_id: str, actor_account_id: int, public_id: str, proposal_public_id: str,
    payload: BillSplitChangeAcceptRequest, idempotency_key: str | None,
) -> BillSplitAgreementResponse:
    def mutate() -> BillSplitAgreementResponse:
        accept_bill_split_change(db, tenant_id=tenant_id, actor_account_id=actor_account_id,
            public_id=public_id, proposal_public_id=proposal_public_id, payload=payload,
            idempotency_key=idempotency_key)
        return get_bill_split_agreement(db, tenant_id=tenant_id, actor_account_id=actor_account_id, public_id=public_id)

    return _execute(db, tenant_id=tenant_id, actor_account_id=actor_account_id, public_id=public_id,
        operation="accept_bill_split_change_proposal", idempotency_key=idempotency_key, payload=payload,
        proposal_public_id=proposal_public_id, response_type=BillSplitAgreementResponse, mutate=mutate)


def _resolve(
    db: Session, *, tenant_id: str, actor_account_id: int, public_id: str, proposal_public_id: str,
    resolution: Literal["rejected", "withdrawn"], operation: str, idempotency_key: str | None,
) -> BillSplitChangeProposalResponse:
    def mutate() -> BillSplitChangeProposalResponse:
        resolve_bill_split_change(db, tenant_id=tenant_id, actor_account_id=actor_account_id,
            public_id=public_id, proposal_public_id=proposal_public_id, resolution=resolution)
        return get_bill_split_change_proposal(db, tenant_id=tenant_id, actor_account_id=actor_account_id,
            public_id=public_id, proposal_public_id=proposal_public_id)

    return _execute(db, tenant_id=tenant_id, actor_account_id=actor_account_id, public_id=public_id,
        operation=operation, idempotency_key=idempotency_key, payload=None,
        proposal_public_id=proposal_public_id, response_type=BillSplitChangeProposalResponse, mutate=mutate)


def reject_bill_split_change_idempotently(
    db: Session, *, tenant_id: str, actor_account_id: int, public_id: str,
    proposal_public_id: str, idempotency_key: str | None,
) -> BillSplitChangeProposalResponse:
    return _resolve(db, tenant_id=tenant_id, actor_account_id=actor_account_id, public_id=public_id,
        proposal_public_id=proposal_public_id, resolution="rejected",
        operation="reject_bill_split_change_proposal", idempotency_key=idempotency_key)


def withdraw_bill_split_change_idempotently(
    db: Session, *, tenant_id: str, actor_account_id: int, public_id: str,
    proposal_public_id: str, idempotency_key: str | None,
) -> BillSplitChangeProposalResponse:
    return _resolve(db, tenant_id=tenant_id, actor_account_id=actor_account_id, public_id=public_id,
        proposal_public_id=proposal_public_id, resolution="withdrawn",
        operation="withdraw_bill_split_change_proposal", idempotency_key=idempotency_key)
