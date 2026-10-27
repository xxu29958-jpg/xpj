package com.ticketbox.domain.model

/** Values consumed by the product; wire names and persistence remain at the repository boundary. */
data class MonthlyArrangementHistory(
    val ledgerId: String,
    val month: String,
    val items: List<MonthlyArrangementHistoryItem>,
    val nextBeforeVersion: Long?,
)

data class MonthlyArrangementHistoryItem(
    val rowVersion: Long,
    val recordedAt: String,
    val homeCurrencyCode: String,
    val savingsTargetCents: Long,
    val reservedBufferCents: Long,
)

data class MonthlyArrangementResponse(
    val ledgerId: String,
    val month: String,
    val arrangement: MonthlyArrangement?,
)

data class MonthlyArrangementChange(
    val homeCurrencyCode: String,
    val savingsTargetCents: Long,
    val reservedBufferCents: Long,
    val expectedRowVersion: Long? = null,
)
