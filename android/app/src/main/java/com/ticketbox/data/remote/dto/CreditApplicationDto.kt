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

@JsonClass(generateAdapter = true)
data class CreditApplicationChoiceDto(
    @param:Json(name = "public_id") val publicId: String,
    val note: String,
    @param:Json(name = "occurred_on") val occurredOn: String,
    @param:Json(name = "remaining_minor") val remainingMinor: Long,
)

@JsonClass(generateAdapter = true)
data class CreditApplicationHistoryDto(
    @param:Json(name = "public_id") val publicId: String,
    @param:Json(name = "credit_note") val creditNote: String,
    @param:Json(name = "draw_note") val drawNote: String,
    @param:Json(name = "amount_minor") val amountMinor: Long,
    @param:Json(name = "applied_minor") val appliedMinor: Long,
    val reason: String,
    @param:Json(name = "created_at") val createdAt: String,
    @param:Json(name = "void_reason") val voidReason: String?,
)

@JsonClass(generateAdapter = true)
data class CreditApplicationsDto(
    val credits: List<CreditApplicationChoiceDto>,
    val obligations: List<CreditApplicationChoiceDto>,
    val history: List<CreditApplicationHistoryDto>,
)
