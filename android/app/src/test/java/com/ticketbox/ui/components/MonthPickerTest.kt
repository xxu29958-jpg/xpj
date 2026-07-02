package com.ticketbox.ui.components

import kotlin.test.Test
import kotlin.test.assertEquals

class MonthPickerTest {
    @Test
    fun displayMonthLabelDropsLeadingZero() {
        assertEquals("2026年7月", displayMonthLabel("2026-07"))
    }

    @Test
    fun displayMonthLabelKeepsUnexpectedValuesReadable() {
        assertEquals("2026", displayMonthLabel("2026"))
        assertEquals("2026-07-extra", displayMonthLabel("2026-07-extra"))
    }
}
