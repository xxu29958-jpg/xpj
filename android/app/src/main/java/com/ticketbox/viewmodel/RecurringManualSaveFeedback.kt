package com.ticketbox.viewmodel

import com.ticketbox.domain.model.UiText

/**
 * Ephemeral ownership for one manual recurring-item submission. This is not a
 * financial fact or an outbox state: it only prevents refresh feedback from
 * impersonating the result of the editor's current write attempt.
 */
data class RecurringManualSaveFeedback(
    val attemptId: Long,
    val settlement: RecurringManualSaveSettlement,
    val message: UiText? = null,
    val requiresOwnerReload: Boolean = false,
)

enum class RecurringManualSaveSettlement {
    InFlight,
    Accepted,
    Failed,
}
