package com.ticketbox.domain.model

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class CreditApplicationChoice(
    @param:Json(name = "public_id") val publicId: String,
    val note: String,
    @param:Json(name = "occurred_on") val occurredOn: String,
    @param:Json(name = "remaining_minor") val remainingMinor: Long,
)

@JsonClass(generateAdapter = true)
data class CreditApplicationHistory(
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
data class CreditApplications(
    val credits: List<CreditApplicationChoice>,
    val obligations: List<CreditApplicationChoice>,
    val history: List<CreditApplicationHistory>,
)
