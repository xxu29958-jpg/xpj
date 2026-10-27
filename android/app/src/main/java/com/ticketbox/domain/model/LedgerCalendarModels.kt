package com.ticketbox.domain.model

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class LedgerCalendar(
    @param:Json(name = "ledger_id") val ledgerId: String,
    val revision: Long,
    @param:Json(name = "timezone_name") val timezoneName: String,
    val basis: String,
    @param:Json(name = "adopted_at") val adoptedAt: String,
)
