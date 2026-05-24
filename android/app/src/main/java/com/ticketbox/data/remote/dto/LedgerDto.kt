package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

/**
 * v0.4-alpha1 multi-ledger DTOs.
 *
 * The mobile app receives [LedgerDto] entries and never deals with the
 * server-side numeric primary key — it identifies a ledger purely by its
 * public [ledgerId] string. Ownership is decided server-side; the client
 * only renders [role] for read-only display.
 */
data class LedgerDto(
    @param:Json(name = "ledger_id")
    val ledgerId: String,
    val name: String,
    val role: String,
    @param:Json(name = "is_default")
    val isDefault: Boolean,
    @param:Json(name = "created_at")
    val createdAt: String?,
    @param:Json(name = "archived_at")
    val archivedAt: String?,
)

data class LedgerListResponseDto(
    val ledgers: List<LedgerDto>,
)

data class LedgerCreateRequestDto(
    val name: String,
)

data class LedgerSwitchResponseDto(
    @param:Json(name = "session_token")
    val sessionToken: String,
    val ledger: LedgerDto,
    @param:Json(name = "account_name")
    val accountName: String,
    @param:Json(name = "device_name")
    val deviceName: String,
    @param:Json(name = "expires_at")
    val expiresAt: String? = null,
    @param:Json(name = "soft_refresh_after")
    val softRefreshAfter: String? = null,
)

data class LedgerMemberDto(
    @param:Json(name = "member_id")
    val memberId: Long,
    @param:Json(name = "account_public_id")
    val accountPublicId: String,
    @param:Json(name = "account_name")
    val accountName: String,
    val role: String,
    @param:Json(name = "created_at")
    val createdAt: String?,
    @param:Json(name = "disabled_at")
    val disabledAt: String?,
    @param:Json(name = "is_self")
    val isSelf: Boolean,
)

data class LedgerMemberListResponseDto(
    val members: List<LedgerMemberDto>,
)

data class LedgerAuditDto(
    @param:Json(name = "public_id")
    val publicId: String,
    @param:Json(name = "ledger_id")
    val ledgerId: String,
    val action: String,
    @param:Json(name = "actor_account_public_id")
    val actorAccountPublicId: String?,
    @param:Json(name = "actor_account_name")
    val actorAccountName: String?,
    @param:Json(name = "target_account_public_id")
    val targetAccountPublicId: String?,
    @param:Json(name = "target_account_name")
    val targetAccountName: String?,
    @param:Json(name = "target_member_id")
    val targetMemberId: Long?,
    @param:Json(name = "invitation_public_id")
    val invitationPublicId: String?,
    @param:Json(name = "previous_role")
    val previousRole: String?,
    @param:Json(name = "new_role")
    val newRole: String?,
    val result: String,
    val detail: String?,
    @param:Json(name = "created_at")
    val createdAt: String?,
)

data class LedgerAuditListResponseDto(
    val items: List<LedgerAuditDto>,
)

data class LedgerMemberRoleUpdateRequestDto(
    val role: String,
)

data class OwnerTransferResponseDto(
    @param:Json(name = "ledger_id")
    val ledgerId: String,
    @param:Json(name = "previous_owner")
    val previousOwner: LedgerMemberDto,
    @param:Json(name = "new_owner")
    val newOwner: LedgerMemberDto,
)

data class InvitationPreviewRequestDto(
    @param:Json(name = "invite_token")
    val inviteToken: String,
)

data class InvitationPreviewResponseDto(
    @param:Json(name = "ledger_id")
    val ledgerId: String,
    @param:Json(name = "ledger_name")
    val ledgerName: String,
    val role: String,
    @param:Json(name = "expires_at")
    val expiresAt: String?,
)

/**
 * v0.4-beta1 family-ledger invitation accept request.
 *
 * Posted to ``/api/invitations/accept`` **without** an Authorization header
 * — the server creates a brand-new Account + Device + LedgerMember row and
 * returns a freshly minted session token that the app must persist before
 * any further calls.
 */
data class InvitationAcceptRequestDto(
    @param:Json(name = "invite_token")
    val inviteToken: String,
    @param:Json(name = "account_name")
    val accountName: String,
    @param:Json(name = "device_name")
    val deviceName: String,
    val platform: String = "android",
)

data class InvitationAcceptResponseDto(
    @param:Json(name = "session_token")
    val sessionToken: String,
    @param:Json(name = "account_name")
    val accountName: String,
    @param:Json(name = "ledger_id")
    val ledgerId: String,
    @param:Json(name = "ledger_name")
    val ledgerName: String,
    @param:Json(name = "device_name")
    val deviceName: String,
    val role: String,
    @param:Json(name = "expires_at")
    val expiresAt: String? = null,
    @param:Json(name = "soft_refresh_after")
    val softRefreshAfter: String? = null,
)
