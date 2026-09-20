"""Participant-scoped JSON adapters for accepted-split agreements."""

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_protocol_writer_context
from app.database import get_db
from app.money_contract_types import MONEY_MINOR_MAX
from app.schemas._bill_split_change import (
    BillSplitAgreementResponse,
    BillSplitChangeAcceptRequest,
    BillSplitChangeCreateRequest,
    BillSplitChangeProposalResponse,
)
from app.services.bill_split_change_command_service import (
    accept_bill_split_change_idempotently,
    create_bill_split_change_idempotently,
    reject_bill_split_change_idempotently,
    withdraw_bill_split_change_idempotently,
)
from app.services.bill_split_service import get_bill_split_agreement
from app.tenants import AuthContext

router = APIRouter(prefix="/api/debts", tags=["debts"])


@router.get("/{public_id}/split-agreement", response_model=BillSplitAgreementResponse)
def get_split_agreement(
    public_id: str,
    new_share_amount_cents: int | None = Query(default=None, ge=0, le=MONEY_MINOR_MAX),
    auth: AuthContext = Depends(get_current_app_context), db: Session = Depends(get_db),
) -> BillSplitAgreementResponse:
    return get_bill_split_agreement(db, tenant_id=auth.tenant_id, actor_account_id=auth.account_id,
        public_id=public_id, new_share_amount_cents=new_share_amount_cents)


@router.post("/{public_id}/split-change-proposals", response_model=BillSplitChangeProposalResponse, status_code=201)
def post_split_change(
    public_id: str, payload: BillSplitChangeCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_protocol_writer_context), db: Session = Depends(get_db),
) -> BillSplitChangeProposalResponse:
    return create_bill_split_change_idempotently(db, tenant_id=auth.tenant_id, actor_account_id=auth.account_id,
        public_id=public_id, payload=payload, idempotency_key=idempotency_key)


@router.post("/{public_id}/split-change-proposals/{proposal_public_id}/accept", response_model=BillSplitAgreementResponse)
def post_accept_split_change(
    public_id: str, proposal_public_id: str, payload: BillSplitChangeAcceptRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_protocol_writer_context), db: Session = Depends(get_db),
) -> BillSplitAgreementResponse:
    return accept_bill_split_change_idempotently(db, tenant_id=auth.tenant_id, actor_account_id=auth.account_id,
        public_id=public_id, proposal_public_id=proposal_public_id, payload=payload, idempotency_key=idempotency_key)


@router.post("/{public_id}/split-change-proposals/{proposal_public_id}/reject", response_model=BillSplitChangeProposalResponse)
def post_reject_split_change(
    public_id: str, proposal_public_id: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_protocol_writer_context), db: Session = Depends(get_db),
) -> BillSplitChangeProposalResponse:
    return reject_bill_split_change_idempotently(db, tenant_id=auth.tenant_id, actor_account_id=auth.account_id,
        public_id=public_id, proposal_public_id=proposal_public_id, idempotency_key=idempotency_key)


@router.post("/{public_id}/split-change-proposals/{proposal_public_id}/withdraw", response_model=BillSplitChangeProposalResponse)
def post_withdraw_split_change(
    public_id: str, proposal_public_id: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_protocol_writer_context), db: Session = Depends(get_db),
) -> BillSplitChangeProposalResponse:
    return withdraw_bill_split_change_idempotently(db, tenant_id=auth.tenant_id, actor_account_id=auth.account_id,
        public_id=public_id, proposal_public_id=proposal_public_id, idempotency_key=idempotency_key)
