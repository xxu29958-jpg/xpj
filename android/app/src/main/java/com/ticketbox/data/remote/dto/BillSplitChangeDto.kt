package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class BillSplitChangeCreateRequestDto(
    @param:Json(name = "new_share_amount_cents") val newShareAmountCents: Long,
    @param:Json(name = "settlement_net_amount_cents") val settlementNetAmountCents: Long,
    @param:Json(name = "reason") val reason: String,
    @param:Json(name = "expected_row_version") val expectedRowVersion: Long,
    @param:Json(name = "expected_return_row_version") val expectedReturnRowVersion: Long? = null,
    @param:Json(name = "supersedes_proposal_public_id") val supersedesProposalPublicId: String? = null,
)

@JsonClass(generateAdapter = true)
data class BillSplitChangeAcceptRequestDto(
    @param:Json(name = "expected_row_version") val expectedRowVersion: Long,
    @param:Json(name = "expected_return_row_version") val expectedReturnRowVersion: Long? = null,
)

@JsonClass(generateAdapter = true)
data class BillSplitChangeProposalDto(
    @param:Json(name = "public_id") val publicId: String,
    @param:Json(name = "original_debt_public_id") val originalDebtPublicId: String,
    @param:Json(name = "return_debt_public_id") val returnDebtPublicId: String? = null,
    @param:Json(name = "status") val status: String,
    @param:Json(name = "proposed_by_you") val proposedByYou: Boolean,
    @param:Json(name = "share_before_amount_cents") val shareBeforeAmountCents: Long,
    @param:Json(name = "new_share_amount_cents") val newShareAmountCents: Long,
    @param:Json(name = "settlement_before_net_amount_cents") val settlementBeforeNetAmountCents: Long,
    @param:Json(name = "settlement_net_amount_cents") val settlementNetAmountCents: Long,
    @param:Json(name = "original_paid_amount_cents") val originalPaidAmountCents: Long,
    @param:Json(name = "return_paid_amount_cents") val returnPaidAmountCents: Long,
    @param:Json(name = "original_forgiven_amount_cents") val originalForgivenAmountCents: Long,
    @param:Json(name = "return_forgiven_amount_cents") val returnForgivenAmountCents: Long,
    @param:Json(name = "original_debt_row_version") val originalDebtRowVersion: Long,
    @param:Json(name = "return_debt_row_version") val returnDebtRowVersion: Long? = null,
    @param:Json(name = "reason") val reason: String,
    @param:Json(name = "created_at") val createdAt: String,
    @param:Json(name = "expires_at") val expiresAt: String,
    @param:Json(name = "resolved_at") val resolvedAt: String? = null,
)

@JsonClass(generateAdapter = true)
data class BillSplitSettlementPreviewDto(
    @param:Json(name = "new_share_amount_cents") val newShareAmountCents: Long,
    @param:Json(name = "default_settlement_net_amount_cents") val defaultSettlementNetAmountCents: Long,
    @param:Json(name = "cash_based_settlement_net_amount_cents") val cashBasedSettlementNetAmountCents: Long?,
    @param:Json(name = "requires_explicit_settlement") val requiresExplicitSettlement: Boolean,
)

data class BillSplitAgreementDto(
    @param:Json(name = "invitation_public_id") val invitationPublicId: String,
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    @param:Json(name = "original_share_amount_cents") val originalShareAmountCents: Long,
    @param:Json(name = "agreed_share_amount_cents") val agreedShareAmountCents: Long,
    @param:Json(name = "original_debt") val originalDebt: DebtDto,
    @param:Json(name = "return_debt") val returnDebt: DebtDto? = null,
    @param:Json(name = "viewer_is_party") val viewerIsParty: Boolean,
    @param:Json(name = "original_paid_amount_cents") val originalPaidAmountCents: Long,
    @param:Json(name = "return_paid_amount_cents") val returnPaidAmountCents: Long,
    @param:Json(name = "original_forgiven_amount_cents") val originalForgivenAmountCents: Long,
    @param:Json(name = "return_forgiven_amount_cents") val returnForgivenAmountCents: Long,
    @param:Json(name = "settlement_net_amount_cents") val settlementNetAmountCents: Long,
    @param:Json(name = "pending_repayment_debt_public_ids") val pendingRepaymentDebtPublicIds: List<String> = emptyList(),
    @param:Json(name = "pending_proposal") val pendingProposal: BillSplitChangeProposalDto? = null,
    @param:Json(name = "preview") val preview: BillSplitSettlementPreviewDto,
)

@JsonClass(generateAdapter = true)
class BillSplitChangeEmptyRequestDto
