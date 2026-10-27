package com.ticketbox.domain.model

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class RecurringDefinition(
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
data class RecurringRecordedDefinition(
    @param:Json(name = "series_row_version") val seriesRowVersion: Long,
    @param:Json(name = "recorded_at") val recordedAt: String,
    val snapshot: RecurringDefinition,
)

@JsonClass(generateAdapter = true)
data class RecurringRevision(
    @param:Json(name = "row_version") val rowVersion: Long,
    @param:Json(name = "change_kind") val changeKind: String,
    @param:Json(name = "recorded_at") val recordedAt: String,
    @param:Json(name = "actor_account_id") val actorAccountId: Long?,
    val snapshot: RecurringDefinition,
)
