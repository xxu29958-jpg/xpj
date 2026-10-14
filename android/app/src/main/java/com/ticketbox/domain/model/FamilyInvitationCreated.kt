package com.ticketbox.domain.model

/**
 * 轴7 发邀请:创建成功后的领域结果。
 *
 * @property inviteToken 邀请明文——**只在创建响应里出现一次**(服务端只存哈希),
 *   UI 必须当场展示/复制,离开页面即不可再取回。
 * @property role 邀请角色(member/viewer)。
 * @property expiresAt 有效期(ISO 8601);null=服务端未返回。
 */
data class FamilyInvitationCreated(
    val inviteToken: String,
    val inviteUrl: String?,
    val role: String,
    val expiresAt: String?,
    val publicId: String? = null,
)

val FamilyInvitationCreated.shareText: String
    get() = inviteUrl?.takeIf { it.isNotBlank() } ?: inviteToken

/** Invitation history contains no token; the original invitation remains the revoke target. */
data class FamilyInvitation(
    val publicId: String,
    val ledgerId: String,
    val role: String,
    val note: String?,
    val createdAt: String?,
    val expiresAt: String?,
    val usedAt: String?,
    val revokedAt: String?,
    val usedByAccountName: String?,
) {
    val canRevoke: Boolean
        get() = usedAt == null && revokedAt == null &&
            runCatching { java.time.Instant.parse(expiresAt).isAfter(java.time.Instant.now()) }.getOrDefault(false)
}
