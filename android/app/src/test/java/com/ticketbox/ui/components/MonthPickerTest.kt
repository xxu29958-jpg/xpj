package com.ticketbox.ui.components

import kotlin.test.Test
import kotlin.test.assertEquals

class MonthPickerTest {
    @Test
    fun monthLabelPartsDropLeadingZero() {
        assertEquals(MonthLabelParts(year = "2026", monthNumber = "7"), monthLabelParts("2026-07"))
    }

    @Test
    fun monthLabelPartsReturnNullForUnexpectedValues() {
        assertEquals(null, monthLabelParts("2026"))
        assertEquals(null, monthLabelParts("2026-07-extra"))
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

    @Test
    fun monthPickerStatusDistinguishesFailureFromLoadedEmpty() {
        assertEquals(
            MonthPickerStatusRowKind.Failed,
            monthPickerStatusRowKind(emptyList(), MonthPickerListState.Failed),
        )
        assertEquals(
            MonthPickerStatusRowKind.Empty,
            monthPickerStatusRowKind(emptyList(), MonthPickerListState.Loaded),
        )
        assertEquals(
            MonthPickerStatusRowKind.Stale,
            monthPickerStatusRowKind(listOf("2026-07"), MonthPickerListState.Failed),
        )
    }
}
