package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

data class RecurringCandidateConfirmRequestDto(
    val merchant: String,
    @param:Json(name = "amount_cents")
    val amountCents: Long,
    @param:Json(name = "occurrence_count")
    val occurrenceCount: Int,
    @param:Json(name = "last_seen_at")
    val lastSeenAt: String?,
    val confidence: String?,
    val frequency: String = "monthly",
    @param:Json(name = "next_expected_date")
    val nextExpectedDate: String? = null,
)

data class RecurringItemDto(
    @param:Json(name = "public_id")
    val publicId: String,
    @param:Json(name = "ledger_id")
    val ledgerId: String,
    val merchant: String,
    @param:Json(name = "merchant_key")
    val merchantKey: String,
    val frequency: String,
    @param:Json(name = "baseline_amount_cents")
    val baselineAmountCents: Long,
    @param:Json(name = "last_amount_cents")
    val lastAmountCents: Long,
    @param:Json(name = "occurrence_count")
    val occurrenceCount: Int,
    @param:Json(name = "last_seen_at")
    val lastSeenAt: String?,
    @param:Json(name = "next_expected_date")
    val nextExpectedDate: String?,
    val status: String,
    val confidence: String?,
    val source: String,
    @param:Json(name = "anomaly_status")
    val anomalyStatus: String = "none",
    @param:Json(name = "current_month_amount_cents")
    val currentMonthAmountCents: Long? = null,
    @param:Json(name = "historical_average_amount_cents")
    val historicalAverageAmountCents: Long? = null,
    @param:Json(name = "amount_delta_percent")
    val amountDeltaPercent: Int? = null,
    @param:Json(name = "created_at")
    val createdAt: String,
    @param:Json(name = "updated_at")
    val updatedAt: String,
    @param:Json(name = "paused_at")
    val pausedAt: String?,
    @param:Json(name = "archived_at")
    val archivedAt: String?,
)

data class RecurringItemListResponseDto(
    val items: List<RecurringItemDto>,
)
