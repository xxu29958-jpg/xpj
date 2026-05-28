"""Identity surface: pairing, ledgers, members, invitations, admin device/link.

Everything an Android/web client needs to authenticate, switch ledgers,
invite/manage members, and view audit trails. Owner-only admin device and
upload-link management also live here because they share the bootstrap/pair
flow.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = [
    "AdminDeviceRenameRequest",
    "AdminDeviceResponse",
    "AdminUploadLinkCreateRequest",
    "AdminUploadLinkResponse",
    "AdminUploadLinkSecretResponse",
    "BootstrapOwnerRequest",
    "BootstrapOwnerResponse",
    "InvitationAcceptRequest",
    "InvitationAcceptResponse",
    "InvitationCreateRequest",
    "InvitationCreateResponse",
    "InvitationListResponse",
    "InvitationPreviewRequest",
    "InvitationPreviewResponse",
    "InvitationSummaryResponse",
    "LedgerAuditListResponse",
    "LedgerAuditResponse",
    "LedgerCreateRequest",
    "LedgerListResponse",
    "LedgerMemberListResponse",
    "LedgerMemberResponse",
    "LedgerMemberRoleUpdateRequest",
    "LedgerResponse",
    "LedgerSwitchResponse",
    "OwnerTransferResponse",
    "PairRequest",
    "PairResponse",
    "PairingCodeCreateRequest",
    "PairingCodeResponse",
    "RefreshSessionResponse",
]


class PairRequest(BaseModel):
    pairing_code: str = Field(min_length=1, max_length=32)
    device_name: str = Field(min_length=1, max_length=120)
    platform: str = Field(min_length=1, max_length=32)


class PairResponse(BaseModel):
    session_token: str
    account_name: str
    ledger_id: str
    ledger_name: str
    device_name: str
    role: str
    # v1.1 Batch 2: app tokens now carry an expiry. ``expires_at`` is
    # ISO-8601 UTC; ``None`` means the token never expires (env opted out).
    # Clients should silently rotate via ``/api/auth/refresh`` once the
    # remaining lifetime drops below ``soft_refresh_after``.
    expires_at: str | None = None
    soft_refresh_after: str | None = None


class RefreshSessionResponse(BaseModel):
    session_token: str
    expires_at: str | None = None
    soft_refresh_after: str | None = None
    rotated: bool


class LedgerResponse(BaseModel):
    ledger_id: str
    name: str
    role: str
    is_default: bool
    created_at: str | None = None
    archived_at: str | None = None


class LedgerListResponse(BaseModel):
    ledgers: list[LedgerResponse]


class LedgerCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class LedgerSwitchResponse(BaseModel):
    session_token: str
    expires_at: str | None = None
    soft_refresh_after: str | None = None
    ledger: LedgerResponse
    account_name: str
    device_name: str


# v0.4-beta1 — family ledger invitations & members
class InvitationCreateRequest(BaseModel):
    role: str = Field(min_length=1, max_length=32)
    note: str | None = Field(default=None, max_length=80)
    ttl_days: int = Field(default=7, ge=1, le=30)


class InvitationSummaryResponse(BaseModel):
    public_id: str
    ledger_id: str
    role: str
    note: str | None = None
    created_at: str | None = None
    expires_at: str | None = None
    used_at: str | None = None
    revoked_at: str | None = None
    used_by_account_name: str | None = None


class InvitationCreateResponse(BaseModel):
    invite_token: str
    invitation: InvitationSummaryResponse


class InvitationListResponse(BaseModel):
    invitations: list[InvitationSummaryResponse]


class InvitationAcceptRequest(BaseModel):
    invite_token: str = Field(min_length=1, max_length=128)
    account_name: str = Field(min_length=1, max_length=120)
    device_name: str = Field(min_length=1, max_length=120)
    platform: str = Field(min_length=1, max_length=32)


class InvitationPreviewRequest(BaseModel):
    invite_token: str = Field(min_length=1, max_length=128)


class InvitationPreviewResponse(BaseModel):
    ledger_id: str
    ledger_name: str
    role: str
    expires_at: str | None = None


class InvitationAcceptResponse(BaseModel):
    session_token: str
    expires_at: str | None = None
    soft_refresh_after: str | None = None
    account_name: str
    ledger_id: str
    ledger_name: str
    device_name: str
    role: str


class LedgerMemberResponse(BaseModel):
    member_id: int
    account_public_id: str
    account_name: str
    role: str
    created_at: str | None = None
    disabled_at: str | None = None
    is_self: bool


class LedgerMemberListResponse(BaseModel):
    members: list[LedgerMemberResponse]


class LedgerMemberRoleUpdateRequest(BaseModel):
    role: str = Field(min_length=1, max_length=32)


class LedgerAuditResponse(BaseModel):
    public_id: str
    ledger_id: str
    action: str
    actor_account_public_id: str | None = None
    actor_account_name: str | None = None
    target_account_public_id: str | None = None
    target_account_name: str | None = None
    target_member_id: int | None = None
    invitation_public_id: str | None = None
    previous_role: str | None = None
    new_role: str | None = None
    result: str
    detail: str | None = None
    created_at: str | None = None


class LedgerAuditListResponse(BaseModel):
    items: list[LedgerAuditResponse]


class OwnerTransferResponse(BaseModel):
    ledger_id: str
    previous_owner: LedgerMemberResponse
    new_owner: LedgerMemberResponse


class BootstrapOwnerRequest(BaseModel):
    account_name: str | None = None
    ledger_name: str | None = None
    device_name: str | None = None
    default_timezone: str | None = None


class BootstrapOwnerResponse(BaseModel):
    account_name: str
    ledger_id: str
    ledger_name: str
    device_name: str
    admin_token: str
    upload_key: str
    upload_url_path: str
    pairing_code: str
    pairing_expires_at: str


class PairingCodeCreateRequest(BaseModel):
    device_name_hint: str | None = None
    ttl_minutes: int = Field(default=15, ge=1, le=60)


class PairingCodeResponse(BaseModel):
    pairing_code: str
    ledger_name: str
    expires_at: str


# v0.3.1-alpha2 Phase 3 / 4 — admin device & UploadLink management.
class AdminDeviceResponse(BaseModel):
    public_id: str
    device_name: str
    platform: str
    account_name: str
    ledger_id: str | None = None
    ledger_name: str | None = None
    last_seen_at: str | None = None
    revoked_at: str | None = None


class AdminDeviceRenameRequest(BaseModel):
    device_name: str = Field(min_length=1, max_length=120)


class AdminUploadLinkResponse(BaseModel):
    public_id: str
    ledger_id: str
    ledger_name: str
    account_name: str
    device_name: str
    default_timezone: str | None = None
    daily_byte_budget: int | None = None
    per_remote_min_interval_seconds: int = 0
    expires_at: str | None = None
    is_expired: bool = False
    masked_url_path: str
    last_used_at: str | None = None
    revoked_at: str | None = None
    created_at: str | None = None


class AdminUploadLinkCreateRequest(BaseModel):
    ledger_id: str | None = None
    default_timezone: str | None = None


class AdminUploadLinkSecretResponse(BaseModel):
    """One-shot reveal returned by create / rotate. The full upload URL is
    only present in this response and never re-served."""

    link: AdminUploadLinkResponse
    upload_url_path: str
    default_timezone: str | None = None
