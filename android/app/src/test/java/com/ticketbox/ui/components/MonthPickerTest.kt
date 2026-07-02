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

    @Test
    fun monthPickerEntriesGroupDynamicMonthsByYear() {
        assertEquals(
            listOf(
                MonthPickerEntry.YearHeader("2026", 0),
                MonthPickerEntry.Month("2026-07"),
                MonthPickerEntry.Month("2026-06"),
                MonthPickerEntry.YearHeader("2025", 1),
                MonthPickerEntry.Month("2025-12"),
            ),
            monthPickerEntries(listOf("2026-07", "2026-06", "2025-12")),
        )
    }

    @Test
    fun monthPickerEntriesDeduplicateAndKeepUnexpectedValuesReadable() {
        assertEquals(
            listOf(
                MonthPickerEntry.YearHeader("2026", 0),
                MonthPickerEntry.Month("2026-07"),
                MonthPickerEntry.Month("bad"),
                MonthPickerEntry.YearHeader("2026", 1),
                MonthPickerEntry.Month("2026-06"),
            ),
            monthPickerEntries(listOf("2026-07", "2026-07", "bad", "2026-06")),
        )
    }
}
