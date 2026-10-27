package com.ticketbox.domain.model

/** Values consumed by the product; wire names and persistence remain at the repository boundary. */
data class ActivityCorrectionPart(
    val accountPublicId: String,
    val accountRowVersion: Long,
    val accountName: String,
    val currencyCode: String,
    val amountMinor: Long,
)
