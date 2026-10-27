package com.ticketbox.domain.model

/** A reminder to reconcile a refused local capture, never a payment or a retryable task. */
data class NotificationCaptureFailure(
    val token: String,
    val occurredAt: String,
    val persistenceFailed: Boolean = false,
)
