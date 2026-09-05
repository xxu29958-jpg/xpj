package com.ticketbox.domain.model

data class InvitationPreview(
    val serverId: String,
    val dataGeneration: String,
    val ledgerId: String,
    val ledgerName: String,
    val role: String,
    val expiresAt: String?,
)

enum class InvitationSessionTarget {
    Unbound,
    CurrentServer,
    ForeignServer,
}
