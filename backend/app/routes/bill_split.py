"""ADR-0029 cross-ledger bill split workflow API.

Two route prefixes:

- ``POST /api/expenses/{id}/split-invite`` — sender creates invitation
  from one of their own expenses.
- ``GET / POST /api/bill-splits/...`` — receiver inbox + sender sent
  list + state transitions (accept / reject / cancel).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.database import get_db
from app.schemas import (
    BillSplitAcceptRequest,
    BillSplitInboxListResponse,
    BillSplitInboxResponse,
    BillSplitInviteRequest,
    BillSplitSentListResponse,
    BillSplitSentResponse,
)
from app.services import bill_split_service as bsplit
from app.tenants import AuthContext

# Sender-side endpoint lives under the expense it splits from.
sender_router = APIRouter(prefix="/api/expenses", tags=["bill-splits"])

# Receiver + sender list / state transitions live under their own prefix.
inbox_router = APIRouter(prefix="/api/bill-splits", tags=["bill-splits"])


@sender_router.post(
    "/{expense_id}/split-invite",
    response_model=BillSplitSentResponse,
    summary="ADR-0029: 发起跨账本拆账邀请",
)
def create_split_invite(
    expense_id: int,
    payload: BillSplitInviteRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> BillSplitSentResponse:
    inv = bsplit.create_invitation(
        db,
        sender_account_id=auth.account_id,
        sender_ledger_id=auth.tenant_id,
        expense_id=expense_id,
        receiver_account_id=payload.receiver_account_id,
        amount_cents=payload.amount_cents,
    )
    return BillSplitSentResponse.model_validate(bsplit.to_sent_response_dict(inv))


@inbox_router.get("/inbox", response_model=BillSplitInboxListResponse)
def list_my_inbox(
    status: str | None = Query(default=None),
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> BillSplitInboxListResponse:
    rows = bsplit.list_inbox(db, receiver_account_id=auth.account_id, status=status)
    return BillSplitInboxListResponse(
        items=[BillSplitInboxResponse.model_validate(bsplit.to_inbox_response_dict(r)) for r in rows]
    )


@inbox_router.get("/sent", response_model=BillSplitSentListResponse)
def list_my_sent(
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> BillSplitSentListResponse:
    rows = bsplit.list_sent(
        db, sender_account_id=auth.account_id, sender_ledger_id=auth.tenant_id
    )
    return BillSplitSentListResponse(
        items=[BillSplitSentResponse.model_validate(bsplit.to_sent_response_dict(r)) for r in rows]
    )


@inbox_router.post(
    "/{public_id}/accept",
    response_model=BillSplitInboxResponse,
    summary="Receiver 接受邀请，选目标账本",
)
def accept_split_invitation(
    public_id: str,
    payload: BillSplitAcceptRequest,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> BillSplitInboxResponse:
    inv, _expense = bsplit.accept_invitation(
        db,
        public_id=public_id,
        accepting_account_id=auth.account_id,
        target_ledger_id=payload.target_ledger_id,
    )
    return BillSplitInboxResponse.model_validate(bsplit.to_inbox_response_dict(inv))


@inbox_router.post(
    "/{public_id}/reject",
    response_model=BillSplitInboxResponse,
)
def reject_split_invitation(
    public_id: str,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> BillSplitInboxResponse:
    inv = bsplit.reject_invitation(
        db, public_id=public_id, rejecting_account_id=auth.account_id
    )
    return BillSplitInboxResponse.model_validate(bsplit.to_inbox_response_dict(inv))


@inbox_router.post(
    "/{public_id}/cancel",
    response_model=BillSplitSentResponse,
)
def cancel_split_invitation(
    public_id: str,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> BillSplitSentResponse:
    inv = bsplit.cancel_invitation(
        db, public_id=public_id, sender_account_id=auth.account_id
    )
    return BillSplitSentResponse.model_validate(bsplit.to_sent_response_dict(inv))


__all__ = ["inbox_router", "sender_router"]
