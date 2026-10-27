package com.ticketbox.domain.model

/** Values consumed by the product; wire names and persistence remain at the repository boundary. */
data class BillSplitAgreement(
    val invitationPublicId: String,
    val homeCurrencyCode: String,
    val originalShareAmountCents: Long,
    val agreedShareAmountCents: Long,
    val originalDebt: Debt,
    val returnDebt: Debt? = null,
    val viewerIsParty: Boolean,
    val originalPaidAmountCents: Long,
    val returnPaidAmountCents: Long,
    val originalForgivenAmountCents: Long,
    val returnForgivenAmountCents: Long,
    val settlementNetAmountCents: Long,
    val pendingRepaymentDebtPublicIds: List<String> = emptyList(),
    val pendingProposal: BillSplitChangeProposal? = null,
    val preview: BillSplitSettlementPreview,
)

data class BillSplitChangeAcceptRequest(
    val expectedRowVersion: Long,
    val expectedReturnRowVersion: Long? = null,
)

data class BillSplitChangeCreateRequest(
    val newShareAmountCents: Long,
    val settlementNetAmountCents: Long,
    val reason: String,
    val expectedRowVersion: Long,
    val expectedReturnRowVersion: Long? = null,
    val supersedesProposalPublicId: String? = null,
)

data class BillSplitChangeProposal(
    val publicId: String,
    val originalDebtPublicId: String,
    val returnDebtPublicId: String? = null,
    val status: String,
    val proposedByYou: Boolean,
    val shareBeforeAmountCents: Long,
    val newShareAmountCents: Long,
    val settlementBeforeNetAmountCents: Long,
    val settlementNetAmountCents: Long,
    val originalPaidAmountCents: Long,
    val returnPaidAmountCents: Long,
    val originalForgivenAmountCents: Long,
    val returnForgivenAmountCents: Long,
    val originalDebtRowVersion: Long,
    val returnDebtRowVersion: Long? = null,
    val reason: String,
    val createdAt: String,
    val expiresAt: String,
    val resolvedAt: String? = null,
)

data class BillSplitSettlementPreview(
    val newShareAmountCents: Long,
    val defaultSettlementNetAmountCents: Long,
    val cashBasedSettlementNetAmountCents: Long?,
    val requiresExplicitSettlement: Boolean,
)
