package com.ticketbox.domain.model

data class FamilyMember(
    val memberId: Long,
    // ADR-0029 拆账发起：内部账号 id，作 split-invite 的 receiver_account_id。
    // 仅用于 API 请求体，绝不展示（守 §3：普通 UI 不暴露任何 id）。
    val accountId: Long,
    val accountPublicId: String,
    val displayName: String,
    val role: String,
    val joinedAt: String?,
    val disabledAt: String?,
    val isSelf: Boolean,
) {
    val isDisabled: Boolean
        get() = !disabledAt.isNullOrBlank()
}

data class OwnerTransferResult(
    val previousOwner: FamilyMember,
    val newOwner: FamilyMember,
)

data class LedgerAuditEntry(
    val publicId: String,
    val action: String,
    val actorName: String?,
    val targetName: String?,
    val targetMemberId: Long?,
    val previousRole: String?,
    val newRole: String?,
    val result: String,
    val createdAt: String?,
)

fun ledgerAuditActionLabel(action: String): String = when (action) {
    "invitation_created" -> "创建邀请"
    "invitation_accepted" -> "接受邀请"
    "invitation_revoked" -> "撤销邀请"
    "member_role_changed" -> "调整角色"
    "member_disabled" -> "停用成员"
    "owner_transferred" -> "转让拥有者"
    else -> "成员变更"
}

fun ledgerAuditResultLabel(result: String): String = when (result) {
    "success" -> "成功"
    "failed", "failure" -> "未完成"
    else -> "已记录"
}
