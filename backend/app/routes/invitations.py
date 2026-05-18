"""Family-ledger invitation & member HTTP routes.

* ``POST /api/ledgers/{ledger_id}/invitations`` — owner mints invite token
* ``GET  /api/ledgers/{ledger_id}/invitations`` — owner lists invites
* ``POST /api/ledgers/{ledger_id}/invitations/{public_id}/revoke`` — owner
* ``POST /api/invitations/preview`` — public; inspect target ledger before accept
* ``POST /api/invitations/accept`` — public; invitee claims token
* ``GET  /api/ledgers/{ledger_id}/members`` — any member of the ledger
* ``POST /api/ledgers/{ledger_id}/members/{member_id}/role`` — owner changes member/viewer
* ``POST /api/ledgers/{ledger_id}/members/{member_id}/disable`` — owner

Authenticated ledger routes use auth dependencies that bind the path
``ledger_id`` to ``AuthContext.ledger_id`` before service code runs. Owner-only
member-management routes use ``get_current_member_manager_context``; read-only
membership routes use ``get_current_ledger_app_context``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_current_ledger_app_context, get_current_member_manager_context
from app.database import get_db
from app.schemas import (
    InvitationAcceptRequest,
    InvitationAcceptResponse,
    InvitationCreateRequest,
    InvitationCreateResponse,
    InvitationListResponse,
    InvitationPreviewRequest,
    InvitationPreviewResponse,
    InvitationSummaryResponse,
    LedgerAuditListResponse,
    LedgerAuditResponse,
    LedgerMemberListResponse,
    LedgerMemberResponse,
    LedgerMemberRoleUpdateRequest,
    OwnerTransferResponse,
)
from app.services.invitation_service import (
    InvitationSummary,
    LedgerAuditSummary,
    MemberSummary,
    accept_invitation,
    create_invitation,
    disable_member,
    list_audit_logs,
    list_invitations,
    list_members,
    preview_invitation,
    revoke_invitation,
    transfer_ledger_owner,
    update_member_role,
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


def _to_audit_response(summary: LedgerAuditSummary) -> LedgerAuditResponse:
    return LedgerAuditResponse(
        public_id=summary.public_id,
        ledger_id=summary.ledger_id,
        action=summary.action,
        actor_account_public_id=summary.actor_account_public_id,
        actor_account_name=summary.actor_account_name,
        target_account_public_id=summary.target_account_public_id,
        target_account_name=summary.target_account_name,
        target_member_id=summary.target_member_id,
        invitation_public_id=summary.invitation_public_id,
        previous_role=summary.previous_role,
        new_role=summary.new_role,
        result=summary.result,
        detail=summary.detail,
        created_at=summary.created_at,
    )


@router.post(
    "/api/ledgers/{ledger_id}/invitations",
    response_model=InvitationCreateResponse,
    status_code=201,
)
def create_invitation_endpoint(
    ledger_id: str,
    payload: InvitationCreateRequest,
    auth: AuthContext = Depends(get_current_member_manager_context),
    db: Session = Depends(get_db),
) -> InvitationCreateResponse:
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
    auth: AuthContext = Depends(get_current_member_manager_context),
    db: Session = Depends(get_db),
) -> InvitationListResponse:
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
    auth: AuthContext = Depends(get_current_member_manager_context),
    db: Session = Depends(get_db),
) -> InvitationSummaryResponse:
    summary = revoke_invitation(
        db,
        ledger_id=ledger_id,
        public_id=public_id,
        actor_account_id=auth.account_id,
    )
    return _to_invitation_response(summary)


@router.post(
    "/api/invitations/preview",
    response_model=InvitationPreviewResponse,
)
def preview_invitation_endpoint(
    payload: InvitationPreviewRequest,
    db: Session = Depends(get_db),
) -> InvitationPreviewResponse:
    result = preview_invitation(db, invite_token=payload.invite_token)
    return InvitationPreviewResponse(
        ledger_id=result.ledger_id,
        ledger_name=result.ledger_name,
        role=result.role,
        expires_at=result.expires_at,
    )


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
    auth: AuthContext = Depends(get_current_ledger_app_context),
    db: Session = Depends(get_db),
) -> LedgerMemberListResponse:
    # Read access for any active member (owner/member/viewer).
    summaries = list_members(db, ledger_id=ledger_id, requester_account_id=auth.account_id)
    return LedgerMemberListResponse(
        members=[_to_member_response(s) for s in summaries]
    )


@router.post(
    "/api/ledgers/{ledger_id}/members/{member_id}/role",
    response_model=LedgerMemberResponse,
)
def update_member_role_endpoint(
    ledger_id: str,
    member_id: int,
    payload: LedgerMemberRoleUpdateRequest,
    auth: AuthContext = Depends(get_current_member_manager_context),
    db: Session = Depends(get_db),
) -> LedgerMemberResponse:
    summary = update_member_role(
        db,
        ledger_id=ledger_id,
        member_id=member_id,
        requester_account_id=auth.account_id,
        role=payload.role,
    )
    return _to_member_response(summary)


@router.post(
    "/api/ledgers/{ledger_id}/members/{member_id}/transfer-owner",
    response_model=OwnerTransferResponse,
)
def transfer_owner_endpoint(
    ledger_id: str,
    member_id: int,
    auth: AuthContext = Depends(get_current_member_manager_context),
    db: Session = Depends(get_db),
) -> OwnerTransferResponse:
    result = transfer_ledger_owner(
        db,
        ledger_id=ledger_id,
        member_id=member_id,
        requester_account_id=auth.account_id,
    )
    return OwnerTransferResponse(
        ledger_id=ledger_id,
        previous_owner=_to_member_response(result.previous_owner),
        new_owner=_to_member_response(result.new_owner),
    )


@router.post(
    "/api/ledgers/{ledger_id}/members/{member_id}/disable",
    response_model=LedgerMemberResponse,
)
def disable_member_endpoint(
    ledger_id: str,
    member_id: int,
    auth: AuthContext = Depends(get_current_member_manager_context),
    db: Session = Depends(get_db),
) -> LedgerMemberResponse:
    summary = disable_member(
        db,
        ledger_id=ledger_id,
        member_id=member_id,
        requester_account_id=auth.account_id,
    )
    return _to_member_response(summary)


@router.get(
    "/api/ledgers/{ledger_id}/audit",
    response_model=LedgerAuditListResponse,
)
def list_audit_endpoint(
    ledger_id: str,
    limit: int = Query(default=100, ge=1, le=200),
    auth: AuthContext = Depends(get_current_member_manager_context),
    db: Session = Depends(get_db),
) -> LedgerAuditListResponse:
    summaries = list_audit_logs(db, ledger_id=ledger_id, limit=limit)
    return LedgerAuditListResponse(items=[_to_audit_response(s) for s in summaries])
