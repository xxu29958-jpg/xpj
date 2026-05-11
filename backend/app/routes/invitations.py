"""Family-ledger invitation & member HTTP routes (v0.4-beta1).

* ``POST /api/ledgers/{ledger_id}/invitations`` — owner mints invite token
* ``GET  /api/ledgers/{ledger_id}/invitations`` — owner lists invites
* ``POST /api/ledgers/{ledger_id}/invitations/{public_id}/revoke`` — owner
* ``POST /api/invitations/accept`` — public; invitee claims token
* ``GET  /api/ledgers/{ledger_id}/members`` — any member of the ledger
* ``POST /api/ledgers/{ledger_id}/members/{member_id}/disable`` — owner

All authenticated routes use ``get_current_app_context`` and enforce role
via :mod:`app.services.permission_service`. Ledger-id from the URL is
cross-checked against ``AuthContext.ledger_id`` so an app token bound to
ledger A cannot administer ledger B.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_current_app_context
from app.database import get_db
from app.errors import AppError
from app.schemas import (
    InvitationAcceptRequest,
    InvitationAcceptResponse,
    InvitationCreateRequest,
    InvitationCreateResponse,
    InvitationListResponse,
    InvitationSummaryResponse,
    LedgerMemberListResponse,
    LedgerMemberResponse,
)
from app.services import permission_service
from app.services.invitation_service import (
    InvitationSummary,
    MemberSummary,
    accept_invitation,
    create_invitation,
    disable_member,
    list_invitations,
    list_members,
    revoke_invitation,
)
from app.tenants import AuthContext


router = APIRouter(tags=["family-ledger"])


def _to_invitation_response(summary: InvitationSummary) -> InvitationSummaryResponse:
    return InvitationSummaryResponse(
        public_id=summary.public_id,
        ledger_id=summary.ledger_id,
        role=summary.role,
        note=summary.note,
        created_at=summary.created_at,
        expires_at=summary.expires_at,
        used_at=summary.used_at,
        revoked_at=summary.revoked_at,
        used_by_account_name=summary.used_by_account_name,
    )


def _to_member_response(summary: MemberSummary) -> LedgerMemberResponse:
    return LedgerMemberResponse(
        member_id=summary.member_id,
        account_public_id=summary.account_public_id,
        account_name=summary.account_name,
        role=summary.role,
        created_at=summary.created_at,
        disabled_at=summary.disabled_at,
        is_self=summary.is_self,
    )


def _require_same_ledger(auth: AuthContext, ledger_id: str) -> None:
    if auth.ledger_id != ledger_id:
        # Same response shape as ledger_not_found to avoid leaking existence.
        raise AppError("ledger_not_found", status_code=404)


@router.post(
    "/api/ledgers/{ledger_id}/invitations",
    response_model=InvitationCreateResponse,
    status_code=201,
)
def create_invitation_endpoint(
    ledger_id: str,
    payload: InvitationCreateRequest,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> InvitationCreateResponse:
    _require_same_ledger(auth, ledger_id)
    permission_service.require_manage_members(auth)
    result = create_invitation(
        db,
        ledger_id=ledger_id,
        role=payload.role,
        created_by_account_id=auth.account_id,
        note=payload.note,
        ttl_days=payload.ttl_days,
    )
    return InvitationCreateResponse(
        invite_token=result.invite_token,
        invitation=_to_invitation_response(result.summary),
    )


@router.get(
    "/api/ledgers/{ledger_id}/invitations",
    response_model=InvitationListResponse,
)
def list_invitations_endpoint(
    ledger_id: str,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> InvitationListResponse:
    _require_same_ledger(auth, ledger_id)
    permission_service.require_manage_members(auth)
    summaries = list_invitations(db, ledger_id=ledger_id)
    return InvitationListResponse(
        invitations=[_to_invitation_response(s) for s in summaries]
    )


@router.post(
    "/api/ledgers/{ledger_id}/invitations/{public_id}/revoke",
    response_model=InvitationSummaryResponse,
)
def revoke_invitation_endpoint(
    ledger_id: str,
    public_id: str,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> InvitationSummaryResponse:
    _require_same_ledger(auth, ledger_id)
    permission_service.require_manage_members(auth)
    summary = revoke_invitation(db, ledger_id=ledger_id, public_id=public_id)
    return _to_invitation_response(summary)


@router.post(
    "/api/invitations/accept",
    response_model=InvitationAcceptResponse,
)
def accept_invitation_endpoint(
    payload: InvitationAcceptRequest,
    db: Session = Depends(get_db),
) -> InvitationAcceptResponse:
    result = accept_invitation(
        db,
        invite_token=payload.invite_token,
        account_name=payload.account_name,
        device_name=payload.device_name,
        platform=payload.platform,
    )
    return InvitationAcceptResponse(
        session_token=result.session_token,
        account_name=result.account_name,
        ledger_id=result.ledger_id,
        ledger_name=result.ledger_name,
        device_name=result.device_name,
        role=result.role,
    )


@router.get(
    "/api/ledgers/{ledger_id}/members",
    response_model=LedgerMemberListResponse,
)
def list_members_endpoint(
    ledger_id: str,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> LedgerMemberListResponse:
    _require_same_ledger(auth, ledger_id)
    # Read access for any active member (owner/member/viewer).
    summaries = list_members(db, ledger_id=ledger_id, requester_account_id=auth.account_id)
    return LedgerMemberListResponse(
        members=[_to_member_response(s) for s in summaries]
    )


@router.post(
    "/api/ledgers/{ledger_id}/members/{member_id}/disable",
    response_model=LedgerMemberResponse,
)
def disable_member_endpoint(
    ledger_id: str,
    member_id: int,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> LedgerMemberResponse:
    _require_same_ledger(auth, ledger_id)
    permission_service.require_manage_members(auth)
    summary = disable_member(
        db,
        ledger_id=ledger_id,
        member_id=member_id,
        requester_account_id=auth.account_id,
    )
    return _to_member_response(summary)
