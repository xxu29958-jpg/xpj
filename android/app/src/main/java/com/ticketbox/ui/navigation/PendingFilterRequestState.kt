package com.ticketbox.ui.navigation

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.ticketbox.ui.screens.pending.NeedsReviewFilter

/**
 * Single-slot request for entering Inbox with a concrete review filter.
 *
 * The request is consumed by PendingRoute after PendingScreen applies it. Keeping it outside
 * MainShellState avoids adding more command methods to the shell and mirrors LedgerDrillState.
 */
internal class PendingFilterRequestState {
    var pending by mutableStateOf<NeedsReviewFilter?>(null)
        private set

    fun post(filter: NeedsReviewFilter) {
        pending = filter
    }

    fun consume(): NeedsReviewFilter? {
        val filter = pending ?: return null
        pending = null
        return filter
    }
}
