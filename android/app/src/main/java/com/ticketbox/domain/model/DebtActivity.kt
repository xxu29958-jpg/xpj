package com.ticketbox.domain.model

/** The server supplies event order and identity; the current Debt supplies the balance. */
data class DebtActivity(
    val kind: String,
    val publicId: String,
    val recordedAt: String,
    val actorDisplayName: String?,
    val actorIsYou: Boolean,
    val amountCents: Long? = null,
    val reason: String? = null,
    val repayment: DebtRepayment? = null,
    val proposal: MemberRepaymentProposal? = null,
) {
    val key: String get() = "$kind:$publicId"
}

data class DebtActivityPage(
    val debtPublicId: String,
    val homeCurrencyCode: String,
    val items: List<DebtActivity>,
    val page: Int,
    val pageSize: Int,
    val total: Int,
)
