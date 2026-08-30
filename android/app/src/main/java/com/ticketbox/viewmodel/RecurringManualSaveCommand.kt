package com.ticketbox.viewmodel

import com.ticketbox.data.repository.RecurringItemDraft
import com.ticketbox.data.repository.RecurringItemPatch
import com.ticketbox.domain.model.RecurringItem

/** One user-owned manual editor intent; create and edit share one settlement owner. */
sealed interface RecurringManualSaveCommand {
    data class Create(val draft: RecurringItemDraft) : RecurringManualSaveCommand
    data class Edit(
        val baseline: RecurringItem,
        val patch: RecurringItemPatch,
    ) : RecurringManualSaveCommand
}
