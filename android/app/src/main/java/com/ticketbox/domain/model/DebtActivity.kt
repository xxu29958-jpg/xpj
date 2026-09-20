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
    val splitChange: DebtSplitChange? = null,
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

/** Immutable agreement-time facts; no client balance calculation. */
data class DebtSplitChange(
    val status: String,
    val shareBeforeAmountCents: Long,
    val newShareAmountCents: Long,
    val settlementNetAmountCents: Long,
    val originalPaidAmountCents: Long,
    val returnPaidAmountCents: Long,
    val originalForgivenAmountCents: Long,
    val returnForgivenAmountCents: Long,
    val reason: String,
)
