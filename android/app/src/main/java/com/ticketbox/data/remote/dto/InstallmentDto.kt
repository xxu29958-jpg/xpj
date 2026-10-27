package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class InstallmentCommandDto(
    @param:Json(name = "expected_row_version") val expectedRowVersion: Long,
    val name: String, val source: String,
    @param:Json(name = "agreed_on") val agreedOn: String,
    @param:Json(name = "supersedes_public_id") val supersedesPublicId: String?,
    @param:Json(name = "draw_public_ids") val drawPublicIds: List<String>,
    val periods: List<InstallmentPeriodInputDto>,
)

@JsonClass(generateAdapter = true)
data class InstallmentPeriodInputDto(
    @param:Json(name = "due_on") val dueOn: String,
    @param:Json(name = "principal_minor") val principalMinor: Long,
    @param:Json(name = "planned_fee_minor") val plannedFeeMinor: Long,
)

@JsonClass(generateAdapter = true)
data class InstallmentPaymentPartDto(
    @param:Json(name = "period_public_id") val periodPublicId: String,
    @param:Json(name = "principal_minor") val principalMinor: Long,
    @param:Json(name = "fee_minor") val feeMinor: Long,
)

@JsonClass(generateAdapter = true)
data class CreditDrawPaymentPartDto(
    @param:Json(name = "draw_public_id") val drawPublicId: String,
    @param:Json(name = "principal_minor") val principalMinor: Long,
)
