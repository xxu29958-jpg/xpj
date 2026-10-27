package com.ticketbox.domain.model

/** Values consumed by the product; wire names and persistence remain at the repository boundary. */
data class RecurringDefinition(
    val merchant: String,
    val merchantKey: String,
    val frequency: String,
    val homeCurrencyCode: String?,
    val baselineAmountCents: Long,
    val nextExpectedDate: String?,
    val status: String,
    val source: String,
)

data class RecurringRecordedDefinition(
    val seriesRowVersion: Long,
    val recordedAt: String,
    val snapshot: RecurringDefinition,
)

data class RecurringRevision(
    val rowVersion: Long,
    val changeKind: String,
    val recordedAt: String,
    val actorAccountId: Long?,
    val snapshot: RecurringDefinition,
)
