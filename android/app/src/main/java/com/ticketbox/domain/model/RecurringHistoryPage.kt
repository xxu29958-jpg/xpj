package com.ticketbox.domain.model

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class RecurringHistoryPage(
    @param:Json(name = "ledger_id") val ledgerId: String,
    @param:Json(name = "public_id") val publicId: String,
    val items: List<RecurringRevision>,
    @param:Json(name = "next_before_version") val nextBeforeVersion: Long?,
)
