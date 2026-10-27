package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class EnvelopeSaveDto(
    @param:Json(name = "expected_row_version") val expectedRowVersion: Long,
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    @param:Json(name = "account_public_ids") val accountPublicIds: List<String>,
    @param:Json(name = "account_row_versions") val accountRowVersions: Map<String, Long>,
    val allocations: Map<String, Long>, val reason: String,
)
