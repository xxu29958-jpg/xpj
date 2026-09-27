package com.ticketbox.domain.model

/** Saved plan definitions; no spending, progress or exchange-rate projection. */
data class GoalDefinition(
    val name: String,
    val goalType: String,
    val period: String,
    val month: String?,
    val category: String?,
    val targetAmountCents: Long?,
    val homeCurrencyCode: String?,
    val status: String,
)

data class GoalRevision(
    val rowVersion: Long,
    val changeKind: String,
    val recordedAt: String,
    val snapshot: GoalDefinition,
)

data class GoalHistoryPage(val items: List<GoalRevision>, val nextBeforeVersion: Long?)
