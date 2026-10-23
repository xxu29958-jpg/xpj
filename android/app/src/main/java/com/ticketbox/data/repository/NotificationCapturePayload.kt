package com.ticketbox.data.repository

import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.domain.model.NotificationDraft
import com.ticketbox.domain.model.NotificationDraftSource
import com.ticketbox.domain.model.RepaymentDraftSource
import com.ticketbox.domain.model.RepaymentNotificationDraft
import com.ticketbox.notification.PaymentNotificationResult
import com.ticketbox.data.remote.dto.NotificationTimeEvidenceDto
import com.ticketbox.data.remote.dto.NotificationFieldEvidenceDto
import com.ticketbox.data.remote.dto.toDto
import java.time.Instant

/** Only parsed payment fields enter Room. The original notification body and system key do not. */
@JsonClass(generateAdapter = true)
data class NotificationCapturePayload(
    val revision: Int,
    val kind: String,
    val notificationKey: String,
    val source: String,
    val originalAmountMinor: Long?,
    val originalCurrencyCode: String,
    val merchant: String?,
    val category: String?,
    val capturedAt: String,
    val parserVersion: String = "legacy",
    val candidates: List<com.ticketbox.data.remote.dto.PaymentCandidateDto> = emptyList(),
    val timeEvidence: NotificationTimeEvidenceDto? = null,
    val fieldEvidence: NotificationFieldEvidenceDto? = null,
) {
    internal fun expenseRequest() = NotificationDraft(NotificationDraftSource.entries.single { it.apiValue == source },
        requireNotNull(originalAmountMinor), merchant, category, capturedAt).toRequest(notificationKey)

    internal fun repaymentRequest() = RepaymentNotificationDraft(RepaymentDraftSource.entries.single { it.apiValue == source },
        requireNotNull(originalAmountMinor), merchant, capturedAt).toCreateRequest(notificationKey)

    internal fun request() = com.ticketbox.data.remote.dto.PaymentCaptureCreateDto(notificationKey, source, capturedAt,
        originalCurrencyCode, originalAmountMinor, merchant, kind, parserVersion, candidates, timeEvidence, fieldEvidence)
}

@JsonClass(generateAdapter = true)
data class NotificationCaptureReceipt(val expenseId: Long? = null, val repaymentPublicId: String? = null,
    val capturePublicId: String? = null)

/** A shared codec for the persisted command, its dispatcher and the existing recovery screen. */
internal object NotificationCaptureWire {
    private val moshi = Moshi.Builder().build()
    val payload = moshi.adapter(NotificationCapturePayload::class.java)
    val receipt = moshi.adapter(NotificationCaptureReceipt::class.java)
}

internal fun PaymentNotificationResult.captureIntent(key: String): PendingMutationIntent {
    require(key.isNotBlank())
    val parsed = when (this) {
        is PaymentNotificationResult.Expense -> NotificationCapturePayload(
            1, "expense", key, draft.source.apiValue, requireNotNull(draft.amountCents), "CNY", draft.merchant?.trim(), draft.category,
            requireNotNull(capturedAt))
        is PaymentNotificationResult.Repayment -> NotificationCapturePayload(
            1, "repayment", key, draft.source.apiValue, draft.amountCents, "CNY", draft.merchantLabel?.trim(), null,
            requireNotNull(draft.capturedAt))
        is PaymentNotificationResult.Review -> NotificationCapturePayload(
            2, "review", key, source, null, "CNY", merchant, null, capturedAt)
    }
    val payload = parsed.copy(revision = 4, parserVersion = com.ticketbox.notification.PaymentNotificationParser.VERSION,
        timeEvidence = timeEvidence?.toDto(),
        fieldEvidence = fieldEvidence?.toDto(),
        candidates = candidates.map { com.ticketbox.data.remote.dto.PaymentCandidateDto(it.kind, it.amountMinor, it.field, it.evidence) })
    require(payload.kind == "review" || (payload.originalAmountMinor ?: 0) > 0)
    Instant.parse(payload.capturedAt)
    return PendingMutationIntent(PendingMutationType.CapturePaymentNotification, "notification:$key", NotificationCaptureWire.payload.toJson(payload), 0, key)
}

internal fun OutboxRow.notificationCapture(): NotificationCapturePayload? = runCatching {
    require(type == PendingMutationType.CapturePaymentNotification && expectedRowVersion == 0L)
    val capture = requireNotNull(NotificationCaptureWire.payload.fromJson(payloadJson))
    require(capture.revision in 1..4 && capture.notificationKey.isNotBlank() && capture.notificationKey == idempotencyKey &&
        targetId == "notification:${capture.notificationKey}")
    require(capture.originalCurrencyCode == "CNY" && (capture.kind == "review" || (capture.originalAmountMinor ?: 0) > 0))
    Instant.parse(capture.capturedAt)
    when (capture.kind) {
        "expense" -> capture.expenseRequest()
        "repayment" -> capture.repaymentRequest()
        "review" -> require(capture.revision >= 2)
        else -> error("Unknown capture kind")
    }
    capture
}.getOrNull()
