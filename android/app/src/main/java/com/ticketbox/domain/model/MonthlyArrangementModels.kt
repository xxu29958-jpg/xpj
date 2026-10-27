package com.ticketbox.domain.model

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class MonthlyArrangementHistory(
    @param:Json(name = "ledger_id") val ledgerId: String,
    val month: String,
    val items: List<MonthlyArrangementHistoryItem>,
    @param:Json(name = "next_before_version") val nextBeforeVersion: Long?,
)

@JsonClass(generateAdapter = true)
data class MonthlyArrangementHistoryItem(
    @param:Json(name = "row_version") val rowVersion: Long,
    @param:Json(name = "recorded_at") val recordedAt: String,
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    @param:Json(name = "savings_target_cents") val savingsTargetCents: Long,
    @param:Json(name = "reserved_buffer_cents") val reservedBufferCents: Long,
)

@JsonClass(generateAdapter = true)
data class MonthlyArrangementResponse(
    @param:Json(name = "ledger_id") val ledgerId: String,
    val month: String,
    val arrangement: MonthlyArrangement?,
)

@JsonClass(generateAdapter = true)
data class MonthlyArrangementChange(
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    @param:Json(name = "savings_target_cents") val savingsTargetCents: Long,
    @param:Json(name = "reserved_buffer_cents") val reservedBufferCents: Long,
    @param:Json(name = "expected_row_version") val expectedRowVersion: Long? = null,
)
