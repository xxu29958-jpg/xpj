package com.ticketbox.ui.screens

import kotlin.test.Test
import kotlin.test.assertEquals

class StatsRefreshIndicatorTest {
    @Test
    fun initialLoadKeepsRefreshIndicatorActive() {
        assertEquals(
            true,
            StatsRefreshIndicator.isActive(loading = true, hasReadableData = false),
        )
    }

    @Test
    fun backgroundRefreshDoesNotHoldRefreshIndicator() {
        assertEquals(
            false,
            StatsRefreshIndicator.isActive(loading = true, hasReadableData = true),
        )
    }
}
