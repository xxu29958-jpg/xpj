package com.ticketbox.ui.navigation

import com.ticketbox.ui.screens.pending.NeedsReviewFilter
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class PendingFilterRequestStateTest {
    @Test
    fun requestIsTypedSingleSlotAndConsumedExactlyOnce() {
        val state = PendingFilterRequestState()
        state.post(NeedsReviewFilter.NeedsAmount)
        state.post(NeedsReviewFilter.NeedsCategory)

        assertEquals(NeedsReviewFilter.NeedsCategory, state.consume())
        assertNull(state.consume())
        assertNull(state.pending)
    }
}
