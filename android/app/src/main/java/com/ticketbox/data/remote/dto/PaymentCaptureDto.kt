package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class PaymentCandidateDto(val kind: String, @Json(name = "amount_minor") val amountMinor: Long?,
    val field: String, val evidence: String)

@JsonClass(generateAdapter = true)
data class PaymentCaptureCreateDto(
    @Json(name = "notification_key") val notificationKey: String, val source: String,
    @Json(name = "captured_at") val capturedAt: String,
    @Json(name = "original_currency") val originalCurrency: String,
    @Json(name = "original_amount_minor") val originalAmountMinor: Long?, val merchant: String?,
    @Json(name = "suggested_kind") val suggestedKind: String,
    @Json(name = "parser_version") val parserVersion: String, val candidates: List<PaymentCandidateDto>,
)

@JsonClass(generateAdapter = true)
data class PaymentCaptureDto(
    @Json(name = "public_id") val publicId: String, @Json(name = "row_version") val rowVersion: Long,
    val source: String, @Json(name = "captured_at") val capturedAt: String,
    @Json(name = "original_currency") val originalCurrency: String,
    @Json(name = "original_amount_minor") val originalAmountMinor: Long?, val merchant: String?, val kind: String,
    @Json(name = "parser_version") val parserVersion: String, val candidates: List<PaymentCandidateDto>,
    @Json(name = "expense_id") val expenseId: Long?,
    @Json(name = "expense_public_id") val expensePublicId: String?,
    @Json(name = "repayment_public_id") val repaymentPublicId: String?,
)

@JsonClass(generateAdapter = true)
data class PaymentCaptureDecisionDto(
    @Json(name = "expected_row_version") val expectedRowVersion: Long, val kind: String,
    @Json(name = "original_currency") val originalCurrency: String,
    @Json(name = "original_amount_minor") val originalAmountMinor: Long?, val merchant: String?, val reason: String,
)

@JsonClass(generateAdapter = true)
data class RepaymentAsExpenseDto(val reason: String, @Json(name = "notification_key") val notificationKey: String?)
