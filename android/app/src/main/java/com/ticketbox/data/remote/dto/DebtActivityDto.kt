package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

/** Participant-visible records, not another balance or command owner. */
data class DebtActivityDto(
    val kind: String,
    @param:Json(name = "public_id") val publicId: String,
    @param:Json(name = "recorded_at") val recordedAt: String,
    @param:Json(name = "actor_display_name") val actorDisplayName: String? = null,
    @param:Json(name = "actor_is_you") val actorIsYou: Boolean,
    @param:Json(name = "amount_cents") val amountCents: Long? = null,
    val reason: String? = null,
    val repayment: RepaymentFactDto? = null,
    val proposal: MemberRepaymentProposalDto? = null,
    @param:Json(name = "split_change") val splitChange: BillSplitChangeProposalDto? = null,
)

data class DebtActivityListDto(
    @param:Json(name = "debt_public_id") val debtPublicId: String,
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    val items: List<DebtActivityDto>,
    val page: Int,
    @param:Json(name = "page_size") val pageSize: Int,
    val total: Int,
)
