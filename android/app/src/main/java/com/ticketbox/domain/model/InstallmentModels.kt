package com.ticketbox.domain.model

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class CreditDrawView(
    @param:Json(name = "public_id") val publicId: String,
    val note: String,
    @param:Json(name = "occurred_on") val occurredOn: String,
    @param:Json(name = "original_minor") val originalMinor: Long,
    @param:Json(name = "remaining_minor") val remainingMinor: Long,
    @param:Json(name = "agreement_public_id") val agreementPublicId: String?,
)

@JsonClass(generateAdapter = true)
data class InstallmentPeriodView(
    @param:Json(name = "public_id") val publicId: String,
    val position: Int,
    @param:Json(name = "due_on") val dueOn: String,
    @param:Json(name = "principal_minor") val principalMinor: Long,
    @param:Json(name = "planned_fee_minor") val plannedFeeMinor: Long,
    @param:Json(name = "paid_principal_minor") val paidPrincipalMinor: Long,
    @param:Json(name = "paid_fee_minor") val paidFeeMinor: Long,
    @param:Json(name = "unincurred_fee_minor") val unincurredFeeMinor: Long = plannedFeeMinor - paidFeeMinor,
    @param:Json(name = "incurred_fee_minor") val incurredFeeMinor: Long? = null,
)

@JsonClass(generateAdapter = true)
data class InstallmentView(
    @param:Json(name = "public_id") val publicId: String,
    @param:Json(name = "series_id") val seriesId: String,
    val revision: Long, val name: String, val source: String,
    @param:Json(name = "agreed_on") val agreedOn: String,
    val active: Boolean,
    @param:Json(name = "needs_review") val needsReview: Boolean,
    @param:Json(name = "remaining_principal_minor") val remainingPrincipalMinor: Long,
    val periods: List<InstallmentPeriodView>,
    @param:Json(name = "draw_public_ids") val drawPublicIds: List<String>,
)

@JsonClass(generateAdapter = true)
data class Installments(
    @param:Json(name = "account_public_id") val accountPublicId: String,
    @param:Json(name = "account_row_version") val accountRowVersion: Long,
    @param:Json(name = "currency_code") val currencyCode: String,
    val agreements: List<InstallmentView>, val draws: List<CreditDrawView>,
)
