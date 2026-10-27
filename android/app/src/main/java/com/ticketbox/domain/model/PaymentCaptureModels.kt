package com.ticketbox.domain.model

import com.squareup.moshi.Json

import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class PaymentCandidate(val kind: String, @Json(name = "amount_minor") val amountMinor: Long?,
    val field: String, val evidence: String)

@JsonClass(generateAdapter = true)
data class PaymentCaptureDecision(
    @Json(name = "expected_row_version") val expectedRowVersion: Long, val kind: String,
    @Json(name = "original_currency") val originalCurrency: String,
    @Json(name = "original_amount_minor") val originalAmountMinor: Long?, val merchant: String?, val reason: String,
)

@JsonClass(generateAdapter = true)
data class PaymentCapture(
    @Json(name = "public_id") val publicId: String, @Json(name = "row_version") val rowVersion: Long,
    val source: String, @Json(name = "captured_at") val capturedAt: String,
    @Json(name = "original_currency") val originalCurrency: String,
    @Json(name = "original_amount_minor") val originalAmountMinor: Long?, val merchant: String?, val kind: String,
    @Json(name = "parser_version") val parserVersion: String, val candidates: List<PaymentCandidate>,
    @Json(name = "expense_id") val expenseId: Long?,
    @Json(name = "expense_public_id") val expensePublicId: String?,
    @Json(name = "repayment_public_id") val repaymentPublicId: String?,
    @Json(name = "recognition_time") val recognitionTime: RecognitionTime? = null,
)
