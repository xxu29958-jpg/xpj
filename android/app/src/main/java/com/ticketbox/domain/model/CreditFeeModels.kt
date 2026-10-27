package com.ticketbox.domain.model

/** Values consumed by the product; wire names and persistence remain at the repository boundary. */
data class CreditFeeView(
    val expenseId: Long,
    val note: String,
    val occurredOn: String,
    val originalMinor: Long,
    val remainingMinor: Long,
    val periodPublicId: String?,
)
