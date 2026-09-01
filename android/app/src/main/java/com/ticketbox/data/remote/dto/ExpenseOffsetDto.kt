package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class ExpenseOffsetCreateRequestDto(
    val kind: ExpenseOffsetKindDto,
    @param:Json(name = "original_amount_minor")
    val originalAmountMinor: Long? = null,
    @param:Json(name = "accounting_date")
    val accountingDate: String,
    val reason: String,
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
)

@JsonClass(generateAdapter = true)
data class ExpenseOffsetVoidRequestDto(
    @param:Json(name = "void_reason")
    val voidReason: String,
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
)

data class ExpenseOffsetResponseDto(
    @param:Json(name = "public_id")
    val publicId: String,
    val kind: ExpenseOffsetKindDto,
    val status: ExpenseOffsetStatusDto,
    @param:Json(name = "original_currency_code")
    val originalCurrencyCode: String,
    @param:Json(name = "original_amount_minor")
    val originalAmountMinor: Long,
    @param:Json(name = "home_currency_code")
    val homeCurrencyCode: String,
    @param:Json(name = "amount_cents")
    val amountCents: Long,
    @param:Json(name = "stream_amount_cents")
    val streamAmountCents: Long,
    @param:Json(name = "stream_sort_time")
    val streamSortTime: String,
    @param:Json(name = "stream_sort_id")
    val streamSortId: Long,
    @param:Json(name = "exchange_rate_to_cny")
    val exchangeRateToCny: String? = null,
    @param:Json(name = "exchange_rate_date")
    val exchangeRateDate: String? = null,
    @param:Json(name = "exchange_rate_source")
    val exchangeRateSource: String? = null,
    @param:Json(name = "accounting_date")
    val accountingDate: String,
    val category: String,
    val reason: String,
    @param:Json(name = "row_version")
    val rowVersion: Long,
    @param:Json(name = "fact_revision")
    val factRevision: Long,
    @param:Json(name = "created_at")
    val createdAt: String,
    @param:Json(name = "updated_at")
    val updatedAt: String,
    @param:Json(name = "voided_at")
    val voidedAt: String? = null,
)

data class ExpenseFinancialSummaryDto(
    @param:Json(name = "gross_original_minor")
    val grossOriginalMinor: Long,
    @param:Json(name = "gross_home_amount_cents")
    val grossHomeAmountCents: Long,
    @param:Json(name = "root_stream_amount_cents")
    val rootStreamAmountCents: Long,
    @param:Json(name = "active_refunded_original_minor")
    val activeRefundedOriginalMinor: Long,
    @param:Json(name = "remaining_refundable_original_minor")
    val remainingRefundableOriginalMinor: Long,
    @param:Json(name = "lineage_home_net_cents")
    val lineageHomeNetCents: Long,
    @param:Json(name = "fx_difference_cents")
    val fxDifferenceCents: Long,
    val status: ExpenseLineageStatusDto,
)

data class CancelledPendingInvitationImpactDto(
    @param:Json(name = "invitation_public_id")
    val invitationPublicId: String,
    @param:Json(name = "cancellation_reason_code")
    val cancellationReasonCode: ExpenseRelationshipReasonDto,
)

data class AcceptedInvitationImpactDto(
    @param:Json(name = "invitation_public_id")
    val invitationPublicId: String,
    @param:Json(name = "source_reason_code")
    val sourceReasonCode: ExpenseRelationshipReasonDto,
    @param:Json(name = "receiver_display_name")
    val receiverDisplayName: String? = null,
    @param:Json(name = "debt_public_id")
    val debtPublicId: String? = null,
    @param:Json(name = "original_agreed_share_home_minor")
    val originalAgreedShareHomeMinor: Long,
    @param:Json(name = "suggested_net_share_home_minor")
    val suggestedNetShareHomeMinor: Long,
    @param:Json(name = "suggested_action")
    val suggestedAction: String,
)

data class ExpenseRelationshipImpactsDto(
    @param:Json(name = "pending_invites_cancelled")
    val pendingInvitesCancelled: List<CancelledPendingInvitationImpactDto> = emptyList(),
    @param:Json(name = "accepted_impacts")
    val acceptedImpacts: List<AcceptedInvitationImpactDto> = emptyList(),
)

data class ExpenseOffsetRevisionDto(
    @param:Json(name = "public_id")
    val publicId: String,
    @param:Json(name = "offset_public_id")
    val offsetPublicId: String,
    @param:Json(name = "revision_number")
    val revisionNumber: Long,
    @param:Json(name = "change_kind")
    val changeKind: ExpenseOffsetChangeKindDto,
    val reason: String,
    @param:Json(name = "actor_account_name")
    val actorAccountName: String? = null,
    @param:Json(name = "actor_device_name")
    val actorDeviceName: String? = null,
    @param:Json(name = "created_at")
    val createdAt: String,
)

data class ExpenseFactBundleDto(
    val root: ExpenseDto,
    @param:Json(name = "financial_summary")
    val financialSummary: ExpenseFinancialSummaryDto,
    @param:Json(name = "active_offsets")
    val activeOffsets: List<ExpenseOffsetResponseDto>,
    @param:Json(name = "recent_history")
    val recentHistory: List<ExpenseOffsetRevisionDto> = emptyList(),
    @param:Json(name = "relationship_impacts")
    val relationshipImpacts: ExpenseRelationshipImpactsDto = ExpenseRelationshipImpactsDto(),
)
