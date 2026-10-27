package com.ticketbox.domain.model

/** Values consumed by the product; wire names and persistence remain at the repository boundary. */
data class CreditApplicationChoice(
    val publicId: String,
    val note: String,
    val occurredOn: String,
    val remainingMinor: Long,
)

data class CreditApplicationHistory(
    val publicId: String,
    val creditNote: String,
    val drawNote: String,
    val amountMinor: Long,
    val appliedMinor: Long,
    val reason: String,
    val createdAt: String,
    val voidReason: String?,
)

data class CreditApplications(
    val credits: List<CreditApplicationChoice>,
    val obligations: List<CreditApplicationChoice>,
    val history: List<CreditApplicationHistory>,
)
