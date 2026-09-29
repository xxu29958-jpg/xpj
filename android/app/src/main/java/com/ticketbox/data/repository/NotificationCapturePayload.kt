package com.ticketbox.data.repository

import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.domain.model.NotificationDraft
import com.ticketbox.domain.model.NotificationDraftSource
import com.ticketbox.domain.model.RepaymentDraftSource
import com.ticketbox.domain.model.RepaymentNotificationDraft
import com.ticketbox.notification.PaymentNotificationResult
import java.time.Instant

/** Only parsed payment fields enter Room. The original notification body and system key do not. */
@JsonClass(generateAdapter = true)
data class NotificationCapturePayload(
    val revision: Int,
    val kind: String,
    val notificationKey: String,
    val source: String,
    val originalAmountMinor: Long,
    val originalCurrencyCode: String,
    val merchant: String?,
    val category: String?,
    val capturedAt: String,
) {
    internal fun expenseRequest() = NotificationDraft(NotificationDraftSource.entries.single { it.apiValue == source },
        originalAmountMinor, merchant, category, capturedAt).toRequest(notificationKey)

    internal fun repaymentRequest() = RepaymentNotificationDraft(RepaymentDraftSource.entries.single { it.apiValue == source },
        originalAmountMinor, merchant, capturedAt).toCreateRequest(notificationKey)
}

@JsonClass(generateAdapter = true)
data class NotificationCaptureReceipt(val expenseId: Long? = null, val repaymentPublicId: String? = null)

/** A shared codec for the persisted command, its dispatcher and the existing recovery screen. */
internal object NotificationCaptureWire {
    private val moshi = Moshi.Builder().build()
    val payload = moshi.adapter(NotificationCapturePayload::class.java)
    val receipt = moshi.adapter(NotificationCaptureReceipt::class.java)
}

internal fun PaymentNotificationResult.captureIntent(key: String): PendingMutationIntent {
    require(key.isNotBlank())
    val payload = when (this) {
        is PaymentNotificationResult.Expense -> NotificationCapturePayload(
            1, "expense", key, draft.source.apiValue, requireNotNull(draft.amountCents), "CNY", draft.merchant?.trim(), draft.category,
            requireNotNull(draft.expenseTime))
        is PaymentNotificationResult.Repayment -> NotificationCapturePayload(
            1, "repayment", key, draft.source.apiValue, draft.amountCents, "CNY", draft.merchantLabel?.trim(), null,
            requireNotNull(draft.capturedAt))
    }
    require(payload.originalAmountMinor > 0)
    Instant.parse(payload.capturedAt)
    return PendingMutationIntent(PendingMutationType.CapturePaymentNotification, "notification:$key", NotificationCaptureWire.payload.toJson(payload), 0, key)
}

internal fun OutboxRow.notificationCapture(): NotificationCapturePayload? = runCatching {
    require(type == PendingMutationType.CapturePaymentNotification && expectedRowVersion == 0L)
    val capture = requireNotNull(NotificationCaptureWire.payload.fromJson(payloadJson))
    require(capture.revision == 1 && capture.notificationKey.isNotBlank() && capture.notificationKey == idempotencyKey &&
        targetId == "notification:${capture.notificationKey}")
    require(capture.originalCurrencyCode == "CNY" && capture.originalAmountMinor > 0)
    Instant.parse(capture.capturedAt)
    when (capture.kind) {
        "expense" -> capture.expenseRequest()
        "repayment" -> capture.repaymentRequest()
        else -> error("Unknown capture kind")
    }
    capture
}.getOrNull()
