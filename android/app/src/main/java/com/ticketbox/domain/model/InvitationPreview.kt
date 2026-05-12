package com.ticketbox.domain.model

data class InvitationPreview(
    val ledgerId: String,
    val ledgerName: String,
    val role: String,
    val expiresAt: String?,
)
