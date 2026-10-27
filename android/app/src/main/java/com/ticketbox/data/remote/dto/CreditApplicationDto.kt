package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class CreditApplicationCreateDto(
    @param:Json(name = "expected_row_version") val expectedRowVersion: Long,
    @param:Json(name = "credit_public_id") val creditPublicId: String,
    @param:Json(name = "draw_public_id") val drawPublicId: String,
    @param:Json(name = "amount_minor") val amountMinor: Long,
    val reason: String,
)

@JsonClass(generateAdapter = true)
data class CreditApplicationVoidDto(
    @param:Json(name = "expected_row_version") val expectedRowVersion: Long,
    @param:Json(name = "review_public_id") val reviewPublicId: String,
    val reason: String,
)
