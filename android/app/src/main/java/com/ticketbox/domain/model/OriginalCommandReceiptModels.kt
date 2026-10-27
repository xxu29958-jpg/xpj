package com.ticketbox.domain.model

data class OriginalCommandReceipt(
    val operation: String,
    val expenseId: Long,
    val publicId: String,
    val rowVersion: Long,
    val acceptedAt: String,
    val sha256: String? = null,
    val cleanupRequestId: String? = null,
    val cleanupPending: Boolean? = null,
)
