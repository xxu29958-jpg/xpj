package com.ticketbox.domain.model

/**
 * Domain-side representation of a ledger the current account belongs to.
 *
 * Mirrors the backend `LedgerResponse` schema. The mobile app never
 * fabricates a [ledgerId] — it always comes from the server.
 */
data class LedgerSummary(
    val ledgerId: String,
    val name: String,
    val role: String,
    val isDefault: Boolean,
    val createdAt: String? = null,
    val archivedAt: String? = null,
)
