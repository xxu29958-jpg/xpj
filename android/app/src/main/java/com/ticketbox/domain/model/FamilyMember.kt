package com.ticketbox.domain.model

data class FamilyMember(
    val memberId: Long,
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
