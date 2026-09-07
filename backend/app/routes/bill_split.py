"""ADR-0029 cross-ledger bill split workflow API.

Two route prefixes:

- ``POST /api/expenses/{id}/split-invite`` — sender creates invitation
  from one of their own expenses.
- ``GET / POST /api/bill-splits/...`` — receiver inbox + sender sent
  list + state transitions (accept / reject / cancel).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_protocol_writer_context
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
from app.services.ledger_service import list_ledgers_for_account
from app.tenants import AuthContext

if TYPE_CHECKING:
    from app.models import BillSplitInvitation

# Sender-side endpoint lives under the expense it splits from.
sender_router = APIRouter(prefix="/api/expenses", tags=["bill-splits"])

# Receiver + sender list / state transitions live under their own prefix.
inbox_router = APIRouter(prefix="/api/bill-splits", tags=["bill-splits"])


def _inbox_responses(
    db: Session, rows: list[BillSplitInvitation], receiver_account_id: int,
) -> list[BillSplitInboxResponse]:
    ledger_names = {
        ledger.ledger_id: ledger.name
        for ledger in list_ledgers_for_account(db, account_id=receiver_account_id)
    } if any(row.status == "accepted" for row in rows) else {}
    return [
        BillSplitInboxResponse.model_validate(bsplit.to_inbox_response_dict(
            row,
            received_bill=bsplit.to_received_bill_reference(
                row, receiver_account_id=receiver_account_id, visible_ledger_names=ledger_names,
            ),
        ))
        for row in rows
    ]


@sender_router.post(
    "/{expense_id}/split-invite",
    response_model=BillSplitSentResponse,
    summary="ADR-0029: 发起跨账本拆账邀请",
)
def create_split_invite(
    expense_id: int,
    payload: BillSplitInviteRequest,
    auth: AuthContext = Depends(get_current_protocol_writer_context),
    idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    db: Session = Depends(get_db),
) -> BillSplitSentResponse:
    inv = bsplit.create_invitation(
        db,
        sender_account_id=auth.account_id,
        sender_ledger_id=auth.tenant_id,
        expense_id=expense_id,
        receiver_account_id=payload.receiver_account_id,
        amount_cents=payload.amount_cents,
        idempotency_key=idempotency_key,
        expected_row_version=payload.expected_row_version,
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
        items=_inbox_responses(db, rows, auth.account_id)
    )


@inbox_router.get("/sent", response_model=BillSplitSentListResponse)
def list_my_sent(
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> BillSplitSentListResponse:
    rows = bsplit.list_sent(
        db, sender_account_id=auth.account_id, sender_ledger_id=auth.tenant_id
    )
    impacted = bsplit.source_impact_pending_invitation_ids(
        db,
        sender_ledger_id=auth.tenant_id,
        invitations=rows,
    )
    return BillSplitSentListResponse(
        items=[
            BillSplitSentResponse.model_validate(
                bsplit.to_sent_response_dict(
                    row,
                    source_impact_pending=row.public_id in impacted,
                )
            )
            for row in rows
        ]
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
        accepting_device_id=auth.device_id,
    )
    return _inbox_responses(db, [inv], auth.account_id)[0]


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
    return _inbox_responses(db, [inv], auth.account_id)[0]


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
