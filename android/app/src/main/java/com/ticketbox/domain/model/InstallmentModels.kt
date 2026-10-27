package com.ticketbox.domain.model

/** Values consumed by the product; wire names and persistence remain at the repository boundary. */
data class CreditDrawView(
    val publicId: String,
    val note: String,
    val occurredOn: String,
    val originalMinor: Long,
    val remainingMinor: Long,
    val agreementPublicId: String?,
)

data class InstallmentPeriodView(
    val publicId: String,
    val position: Int,
    val dueOn: String,
    val principalMinor: Long,
    val plannedFeeMinor: Long,
    val paidPrincipalMinor: Long,
    val paidFeeMinor: Long,
    val unincurredFeeMinor: Long = plannedFeeMinor - paidFeeMinor,
    val incurredFeeMinor: Long? = null,
)

data class InstallmentView(
    val publicId: String,
    val seriesId: String,
    val revision: Long, val name: String, val source: String,
    val agreedOn: String,
    val active: Boolean,
    val needsReview: Boolean,
    val remainingPrincipalMinor: Long,
    val periods: List<InstallmentPeriodView>,
    val drawPublicIds: List<String>,
)

data class Installments(
    val accountPublicId: String,
    val accountRowVersion: Long,
    val currencyCode: String,
    val agreements: List<InstallmentView>, val draws: List<CreditDrawView>,
)
