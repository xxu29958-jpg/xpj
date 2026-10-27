package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class CreditFeeCreateDto(
    @param:Json(name = "expected_row_version") val expectedRowVersion: Long,
    @param:Json(name = "calendar_revision") val calendarRevision: Long,
    @param:Json(name = "amount_minor") val amountMinor: Long,
    @param:Json(name = "occurred_on") val occurredOn: String,
    val note: String,
    @param:Json(name = "period_public_id") val periodPublicId: String? = null,
)

@JsonClass(generateAdapter = true)
data class CreditFeePaymentPartDto(
    @param:Json(name = "expense_id") val expenseId: Long,
    @param:Json(name = "amount_minor") val amountMinor: Long,
)
