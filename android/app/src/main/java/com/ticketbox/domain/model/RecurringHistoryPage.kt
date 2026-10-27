package com.ticketbox.domain.model

data class RecurringHistoryPage(
    val ledgerId: String,
    val publicId: String,
    val items: List<RecurringRevision>,
    val nextBeforeVersion: Long?,
)
