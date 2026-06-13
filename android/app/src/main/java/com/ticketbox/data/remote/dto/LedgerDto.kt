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
    // ADR-0029 拆账发起：后端成员 API 现带内部 account_id，用作 split-invite 的
    // receiver_account_id。映射到 domain FamilyMember.accountId，不上 UI（守 §3）。
    @param:Json(name = "account_id")
    val accountId: Long,
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

/**
 * 轴7 发邀请:``POST /api/ledgers/{ledger_id}/invitations`` 请求体(owner 级)。
 * 后端 ``InvitationCreateRequest`` 为 extra=forbid,字段集必须严格对齐;
 * role 只接受 member/viewer(repository 层先校验,后端 403/422 兜底)。
 */
data class InvitationCreateRequestDto(
    val role: String,
    val note: String? = null,
    @param:Json(name = "ttl_days")
    val ttlDays: Int = 7,
)

/** 邀请摘要(创建响应内嵌;后端 ``InvitationSummaryResponse``)。 */
data class InvitationSummaryDto(
    @param:Json(name = "public_id")
    val publicId: String,
    @param:Json(name = "ledger_id")
    val ledgerId: String,
    val role: String,
    val note: String? = null,
    @param:Json(name = "created_at")
    val createdAt: String? = null,
    @param:Json(name = "expires_at")
    val expiresAt: String? = null,
    @param:Json(name = "used_at")
    val usedAt: String? = null,
    @param:Json(name = "revoked_at")
    val revokedAt: String? = null,
    @param:Json(name = "used_by_account_name")
    val usedByAccountName: String? = null,
)

/**
 * 创建邀请响应(后端 ``InvitationCreateResponse``)。``invite_token`` 是**唯一一次**
 * 返回的明文(服务端只存哈希)——UI 必须当场展示/复制,离开即不可再取。
 */
data class InvitationCreateResponseDto(
    @param:Json(name = "invite_token")
    val inviteToken: String,
    val invitation: InvitationSummaryDto,
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
