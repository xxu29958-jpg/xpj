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

@JsonClass(generateAdapter = true)
data class InstallmentPeriodViewDto(
    @param:Json(name = "public_id") val publicId: String,
    val position: Int,
    @param:Json(name = "due_on") val dueOn: String,
    @param:Json(name = "principal_minor") val principalMinor: Long,
    @param:Json(name = "planned_fee_minor") val plannedFeeMinor: Long,
    @param:Json(name = "paid_principal_minor") val paidPrincipalMinor: Long,
    @param:Json(name = "paid_fee_minor") val paidFeeMinor: Long,
    @param:Json(name = "unincurred_fee_minor") val unincurredFeeMinor: Long = plannedFeeMinor - paidFeeMinor,
)

@JsonClass(generateAdapter = true)
data class InstallmentViewDto(
    @param:Json(name = "public_id") val publicId: String,
    @param:Json(name = "series_id") val seriesId: String,
    val revision: Long, val name: String, val source: String,
    @param:Json(name = "agreed_on") val agreedOn: String,
    val active: Boolean,
    @param:Json(name = "needs_review") val needsReview: Boolean,
    @param:Json(name = "remaining_principal_minor") val remainingPrincipalMinor: Long,
    val periods: List<InstallmentPeriodViewDto>,
    @param:Json(name = "draw_public_ids") val drawPublicIds: List<String>,
)

@JsonClass(generateAdapter = true)
data class CreditDrawViewDto(
    @param:Json(name = "public_id") val publicId: String,
    val note: String,
    @param:Json(name = "occurred_on") val occurredOn: String,
    @param:Json(name = "original_minor") val originalMinor: Long,
    @param:Json(name = "remaining_minor") val remainingMinor: Long,
    @param:Json(name = "agreement_public_id") val agreementPublicId: String?,
)

@JsonClass(generateAdapter = true)
data class InstallmentsDto(
    @param:Json(name = "account_public_id") val accountPublicId: String,
    @param:Json(name = "account_row_version") val accountRowVersion: Long,
    @param:Json(name = "currency_code") val currencyCode: String,
    val agreements: List<InstallmentViewDto>, val draws: List<CreditDrawViewDto>,
)
