package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

/** Immutable Series definition, without current observations, due dates or reservations. */
@JsonClass(generateAdapter = true)
data class RecurringDefinitionDto(
    val merchant: String,
    @param:Json(name = "merchant_key") val merchantKey: String,
    val frequency: String,
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String?,
    @param:Json(name = "baseline_amount_cents") val baselineAmountCents: Long,
    @param:Json(name = "next_expected_date") val nextExpectedDate: String?,
    val status: String,
    val source: String,
)

@JsonClass(generateAdapter = true)
data class RecurringRevisionDto(
    @param:Json(name = "row_version") val rowVersion: Long,
    @param:Json(name = "change_kind") val changeKind: String,
    @param:Json(name = "recorded_at") val recordedAt: String,
    @param:Json(name = "actor_account_id") val actorAccountId: Long?,
    val snapshot: RecurringDefinitionDto,
)

@JsonClass(generateAdapter = true)
data class RecurringHistoryPageDto(
    @param:Json(name = "ledger_id") val ledgerId: String,
    @param:Json(name = "public_id") val publicId: String,
    val items: List<RecurringRevisionDto>,
    @param:Json(name = "next_before_version") val nextBeforeVersion: Long?,
)

@JsonClass(generateAdapter = true)
data class RecurringRecordedDefinitionDto(
    @param:Json(name = "series_row_version") val seriesRowVersion: Long,
    @param:Json(name = "recorded_at") val recordedAt: String,
    val snapshot: RecurringDefinitionDto,
)
