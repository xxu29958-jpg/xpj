package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass
import com.ticketbox.domain.model.BillSplitChangeProposal
import com.ticketbox.domain.model.BillSplitSettlementPreview

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
    @param:Json(name = "pending_proposal") val pendingProposal: BillSplitChangeProposal? = null,
    @param:Json(name = "preview") val preview: BillSplitSettlementPreview,
)

@JsonClass(generateAdapter = true)
class BillSplitChangeEmptyRequestDto
