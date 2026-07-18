package com.ticketbox.domain.model

/** Server-defined repayment fact states. Unknown future states stay read-only in the UI. */
object DebtRepaymentFactStatuses {
    const val ACTIVE = "active"
    const val VOIDED = "voided"
}

/** Append-only correction attached to one mistaken repayment. */
data class DebtRepaymentVoidFact(
    val publicId: String,
    val reason: String,
    val createdAt: String,
)

/**
 * One committed repayment from the canonical history read model.
 *
 * [isActive] deliberately requires both the explicit active state and the absence of a void fact.
 * A malformed or future server state therefore cannot accidentally enable the destructive
 * repayment-void action.
 */
data class DebtRepaymentRecord(
    val publicId: String,
    val amountCents: Long,
    val originalCurrencyCode: String?,
    val originalAmountMinor: Long?,
    val exchangeRateToCny: String?,
    val exchangeRateDate: String?,
    val exchangeRateSource: String?,
    val paidAt: String,
    val createdAt: String,
    val status: String,
    val voidFact: DebtRepaymentVoidFact?,
) {
    val isActive: Boolean
        get() = status == DebtRepaymentFactStatuses.ACTIVE && voidFact == null

    val isVoided: Boolean
        get() = status == DebtRepaymentFactStatuses.VOIDED && voidFact != null
}

/** Loaded canonical pages plus pagination metadata returned by the backend. */
data class DebtRepaymentHistory(
    val debtPublicId: String,
    val homeCurrencyCode: String,
    val items: List<DebtRepaymentRecord>,
    val page: Int,
    val pageSize: Int,
    val total: Int,
) {
    /** The server page window, rather than only the deduplicated item count, controls pagination. */
    val hasMore: Boolean
        get() = pageSize > 0 &&
            page.toLong() * pageSize.toLong() < total.toLong() &&
            items.size < total
}
