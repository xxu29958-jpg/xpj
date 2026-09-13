package com.ticketbox.data.repository

import com.ticketbox.domain.model.RecurringItem

data class RecurringItemDraft(
    val merchant: String,
    val baselineAmountCents: Long,
    val nextExpectedDate: String?,
    val homeCurrencyCode: String,
)

data class RecurringDateEdit(
    val changed: Boolean,
    val value: String?,
) {
    companion object {
        fun unchanged(): RecurringDateEdit = RecurringDateEdit(changed = false, value = null)
        fun changed(value: String?): RecurringDateEdit = RecurringDateEdit(changed = true, value = value)
    }
}

data class RecurringItemPatch(
    val merchant: String? = null,
    val baselineAmountCents: Long? = null,
    val nextExpectedDate: RecurringDateEdit = RecurringDateEdit.unchanged(),
    val homeCurrencyCode: String,
)

enum class RecurringPendingKind {
    CREATE,
    UPDATE,
}

enum class RecurringPendingState {
    WAITING,
    CONFLICT,
    FAILED,
    DONE,
}

/**
 * A durable local intent, not a published recurring-item fact. UI consumers may
 * show it as waiting for sync, but must not include it in committed totals or
 * reminders until the server returns a [RecurringItem].
 */
data class RecurringPendingIntent(
    val kind: RecurringPendingKind,
    val targetId: String,
    val idempotencyKey: String,
    val state: RecurringPendingState = RecurringPendingState.WAITING,
    val publicId: String? = null,
    val merchant: String? = null,
    val baselineAmountCents: Long? = null,
    val nextExpectedDateChanged: Boolean = false,
    val nextExpectedDate: String? = null,
    val homeCurrencyCode: String? = null,
    val hasSupportedIntent: Boolean = false,
    val canRetry: Boolean = false,
)
