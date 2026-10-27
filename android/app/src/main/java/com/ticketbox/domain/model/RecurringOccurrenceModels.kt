package com.ticketbox.domain.model

/** Values consumed by the product; wire names and persistence remain at the repository boundary. */
data class RecurringOccurrence(
    val seriesPublicId: String,
    val period: String,
    val seriesRowVersion: Long,
    val rowVersion: Long,
    val state: String,
    val plannedAmountCents: Long,
    val reservedAmountCents: Long,
    val expensePublicId: String?,
    val paidAmountCents: Long?,
    val nextDueDate: String?,
    val expenseId: Long? = null,
    val homeCurrencyCode: String? = null,
    val paidHomeCurrencyCode: String? = null,
    val recordedDefinition: RecurringRecordedDefinition? = null,
    val paymentReviewReason: String? = null,
)

data class RecurringOccurrencePaymentRequest(
    val action: String,
    val expectedRowVersion: Long,
    val expectedSeriesRowVersion: Long,
    val expensePublicId: String? = null,
    val expectedExpenseRowVersion: Long? = null,
)
