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
    val role: String,
    val expiresAt: String?,
)
