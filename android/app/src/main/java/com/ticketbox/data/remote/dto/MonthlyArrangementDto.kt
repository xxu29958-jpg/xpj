package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class MonthlyArrangementDto(
    @param:Json(name = "ledger_id") val ledgerId: String,
    val month: String,
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    @param:Json(name = "savings_target_cents") val savingsTargetCents: Long,
    @param:Json(name = "reserved_buffer_cents") val reservedBufferCents: Long,
    @param:Json(name = "row_version") val rowVersion: Long,
    @param:Json(name = "updated_at") val updatedAt: String,
)
@JsonClass(generateAdapter = true)
data class MonthlyArrangementSaveRequest(
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    @param:Json(name = "savings_target_cents") val savingsTargetCents: Long,
    @param:Json(name = "reserved_buffer_cents") val reservedBufferCents: Long,
    @param:Json(name = "expected_row_version") val expectedRowVersion: Long? = null,
)
@JsonClass(generateAdapter = true)
data class MonthlyArrangementResponseDto(
    @param:Json(name = "ledger_id") val ledgerId: String,
    val month: String,
    val arrangement: MonthlyArrangementDto?,
)
@JsonClass(generateAdapter = true)
data class MonthlyArrangementHistoryItemDto(
    @param:Json(name = "row_version") val rowVersion: Long,
    @param:Json(name = "recorded_at") val recordedAt: String,
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    @param:Json(name = "savings_target_cents") val savingsTargetCents: Long,
    @param:Json(name = "reserved_buffer_cents") val reservedBufferCents: Long,
)
@JsonClass(generateAdapter = true)
data class MonthlyArrangementHistoryDto(
    @param:Json(name = "ledger_id") val ledgerId: String,
    val month: String,
    val items: List<MonthlyArrangementHistoryItemDto>,
    @param:Json(name = "next_before_version") val nextBeforeVersion: Long?,
)
