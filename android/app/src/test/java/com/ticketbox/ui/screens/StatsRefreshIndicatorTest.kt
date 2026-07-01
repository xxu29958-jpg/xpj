package com.ticketbox.ui.screens

import kotlin.test.Test
import kotlin.test.assertEquals

class ReadableRefreshIndicatorTest {
    @Test
    fun initialLoadKeepsRefreshIndicatorActive() {
        assertEquals(
            true,
            ReadableRefreshIndicator.isActive(loading = true, hasReadableData = false),
        )
    }

    @Test
    fun backgroundRefreshDoesNotHoldRefreshIndicator() {
        assertEquals(
            false,
            ReadableRefreshIndicator.isActive(loading = true, hasReadableData = true),
        )
    }
}
