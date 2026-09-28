package com.ticketbox.domain.model

data class IncomeHistoryPage(val items: List<IncomeRevision>, val nextBeforeVersion: Long?)

data class IncomeRevision(
    val rowVersion: Long,
    val changeKind: String,
    val recordedAt: String,
    val intentMonth: String?,
    val effectiveMonth: String?,
    val snapshot: IncomeDefinition,
)

data class IncomeDefinition(
    val label: String,
    val sourceType: String,
    val frequency: String,
    val incomeMonth: String?,
    val amountCents: Long,
    val homeCurrencyCode: String?,
    val payDay: Int,
    val status: String,
)
