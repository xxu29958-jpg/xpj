package com.ticketbox.domain.model

data class RecurringItem(
    val publicId: String,
    val ledgerId: String,
    val merchant: String,
    val merchantKey: String,
    val frequency: String,
    val baselineAmountCents: Long,
    val lastAmountCents: Long,
    val occurrenceCount: Int,
    val lastSeenAt: String?,
    val nextExpectedDate: String?,
    val status: String,
    val confidence: String?,
    val source: String,
    val createdAt: String,
    val updatedAt: String,
    val pausedAt: String?,
    val archivedAt: String?,
)
