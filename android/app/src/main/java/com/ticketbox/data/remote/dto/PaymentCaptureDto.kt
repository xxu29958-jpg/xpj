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
    @Json(name = "time_evidence") val timeEvidence: NotificationTimeEvidenceDto? = null,
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
    @Json(name = "recognition_time") val recognitionTime: RecognitionTimeDto? = null,
)

@JsonClass(generateAdapter = true)
data class PaymentCaptureDecisionDto(
    @Json(name = "expected_row_version") val expectedRowVersion: Long, val kind: String,
    @Json(name = "original_currency") val originalCurrency: String,
    @Json(name = "original_amount_minor") val originalAmountMinor: Long?, val merchant: String?, val reason: String,
)

@JsonClass(generateAdapter = true)
data class RepaymentAsExpenseDto(val reason: String, @Json(name = "notification_key") val notificationKey: String?,
    @Json(name = "correction_versions") val correctionVersions: RepaymentCorrectionVersionsDto? = null,
    @Json(name = "expense_currency") val expenseCurrency: String? = null,
    @Json(name = "expense_amount_minor") val expenseAmountMinor: Long? = null)

@JsonClass(generateAdapter = true)
data class RepaymentCorrectionVersionsDto(
    @Json(name = "debt_row_version") val debtRowVersion: Long,
    @Json(name = "source_expense_row_version") val sourceExpenseRowVersion: Long? = null,
    @Json(name = "source_offset_row_version") val sourceOffsetRowVersion: Long? = null,
    @Json(name = "funds_account_versions") val fundsAccountVersions: Map<String, Long> = emptyMap(),
    @Json(name = "fee_expense_versions") val feeExpenseVersions: Map<String, Long> = emptyMap(),
)
