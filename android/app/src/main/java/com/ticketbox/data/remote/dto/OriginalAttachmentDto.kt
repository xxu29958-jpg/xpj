package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class OriginalVerificationRequestDto(
    @param:Json(name = "expected_row_version") val expectedRowVersion: Long,
    @param:Json(name = "reviewed_sha256") val reviewedSha256: String,
)

@JsonClass(generateAdapter = true)
data class OriginalCleanupRequestDto(
    @param:Json(name = "expected_row_version") val expectedRowVersion: Long,
    @param:Json(name = "request_id") val requestId: String,
)
