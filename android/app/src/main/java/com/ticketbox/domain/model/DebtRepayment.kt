package com.ticketbox.domain.model

object DebtRepaymentStatuses {
    const val ACTIVE = "active"
    const val VOIDED = "voided"
}

/** A committed payment and its optional append-only correction; never a derived balance. */
data class DebtRepayment(
    val publicId: String,
    val amountCents: Long,
    val paidAt: String,
    val createdAt: String,
    val status: String,
    val voidFact: DebtRepaymentVoid? = null,
    val originalCurrencyCode: String? = null,
    val originalAmountMinor: Long? = null,
) {
    val isActive: Boolean get() = status == DebtRepaymentStatuses.ACTIVE
}

data class DebtRepaymentVoid(val publicId: String, val reason: String, val createdAt: String)

data class DebtRepaymentPage(
    val debtPublicId: String,
    val homeCurrencyCode: String,
    val items: List<DebtRepayment>,
    val page: Int,
    val pageSize: Int,
    val total: Int,
)
