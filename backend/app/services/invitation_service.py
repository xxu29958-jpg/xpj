"""Family-ledger invitation service public facade.

Routes and tests import this module as the stable service boundary. The
implementation is split by responsibility across smaller modules:

* ``invitation_invites`` owns invite token create/list/revoke/preview/accept.
* ``invitation_members`` owns member role, disable, and owner-transfer flows.
* ``invitation_audit`` owns ledger audit-log shaping and listing.
* ``invitation_common`` owns shared constants and role/membership helpers.
"""

from __future__ import annotations

from app.services.identity_service import new_session_token  # noqa: F401
from app.services.invitation_audit import (
    LedgerAuditSummary,
    account_identity,
    add_audit_log,
    audit_summary,
    clean_detail,
    list_audit_logs,
)
from app.services.invitation_common import (
    AUDIT_INVITATION_ACCEPTED,
    AUDIT_INVITATION_CREATED,
    AUDIT_INVITATION_REVOKED,
    AUDIT_MEMBER_DISABLED,
    AUDIT_MEMBER_ROLE_CHANGED,
    AUDIT_OWNER_TRANSFERRED,
    INVITATION_TOKEN_PREFIX,
    INVITATION_TTL_DAYS,
    active_member_by_id,
    active_member_for_account,
    clean_note,
    new_invite_token,
    require_active_owner,
)
from app.services.invitation_invites import (
    AcceptInvitationResult,
    CreateInvitationResult,
    InvitationPreviewResult,
    InvitationSummary,
    accept_invitation,
    create_invitation,
    invitation_summary,
    list_invitations,
    preview_invitation,
    resolve_active_invitation,
    revoke_invitation,
)
from app.services.invitation_members import (
    MemberSummary,
    OwnerTransferResult,
    disable_member,
    list_members,
    transfer_ledger_owner,
    update_member_role,
)

# Backward-compatible aliases for older tests that imported private helpers.
_account_identity = account_identity
_active_member_by_id = active_member_by_id
_active_member_for_account = active_member_for_account
_add_audit_log = add_audit_log
_audit_summary = audit_summary
_clean_detail = clean_detail
_clean_note = clean_note
_require_active_owner = require_active_owner
_resolve_active_invitation = resolve_active_invitation
_summary = invitation_summary


__all__ = [
    "AUDIT_INVITATION_ACCEPTED",
    "AUDIT_INVITATION_CREATED",
    "AUDIT_INVITATION_REVOKED",
    "AUDIT_MEMBER_DISABLED",
    "AUDIT_MEMBER_ROLE_CHANGED",
    "AUDIT_OWNER_TRANSFERRED",
    "INVITATION_TOKEN_PREFIX",
    "INVITATION_TTL_DAYS",
    "AcceptInvitationResult",
    "CreateInvitationResult",
    "InvitationPreviewResult",
    "InvitationSummary",
    "LedgerAuditSummary",
    "MemberSummary",
    "OwnerTransferResult",
    "accept_invitation",
    "create_invitation",
    "disable_member",
    "list_audit_logs",
    "list_invitations",
    "list_members",
    "new_invite_token",
    "new_session_token",
    "preview_invitation",
    "revoke_invitation",
    "transfer_ledger_owner",
    "update_member_role",
]
