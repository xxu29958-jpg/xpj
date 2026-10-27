package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class AccountActivityVoidDto(
    @param:Json(name = "expected_row_version") val expectedRowVersion: Long,
    @param:Json(name = "event_public_id") val eventPublicId: String,
    @param:Json(name = "account_row_versions") val accountRowVersions: Map<String, Long>,
    @param:Json(name = "occurred_on") val occurredOn: String,
    val reason: String,
)
