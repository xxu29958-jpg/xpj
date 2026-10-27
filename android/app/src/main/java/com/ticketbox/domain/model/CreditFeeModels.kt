package com.ticketbox.domain.model

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class CreditFeeView(
    @param:Json(name = "expense_id") val expenseId: Long,
    val note: String,
    @param:Json(name = "occurred_on") val occurredOn: String,
    @param:Json(name = "original_minor") val originalMinor: Long,
    @param:Json(name = "remaining_minor") val remainingMinor: Long,
    @param:Json(name = "period_public_id") val periodPublicId: String?,
)
