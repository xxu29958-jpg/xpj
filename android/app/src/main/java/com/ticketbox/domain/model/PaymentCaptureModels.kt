package com.ticketbox.domain.model

/** Values consumed by the product; wire names and persistence remain at the repository boundary. */
data class PaymentCandidate(
    val kind: String, val amountMinor: Long?,
    val field: String, val evidence: String
)

data class PaymentCaptureDecision(
    val expectedRowVersion: Long, val kind: String,
    val originalCurrency: String,
    val originalAmountMinor: Long?, val merchant: String?, val reason: String,
)

data class PaymentCapture(
    val publicId: String, val rowVersion: Long,
    val source: String, val capturedAt: String,
    val originalCurrency: String,
    val originalAmountMinor: Long?, val merchant: String?, val kind: String,
    val parserVersion: String, val candidates: List<PaymentCandidate>,
    val expenseId: Long?,
    val expensePublicId: String?,
    val repaymentPublicId: String?,
    val recognitionTime: RecognitionTime? = null,
)
