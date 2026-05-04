package com.ticketbox.ui.components

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue
import java.time.LocalDate
import java.time.ZoneOffset

class FormattersTest {
    @Test
    fun parsesYuanInputToCents() {
        assertEquals(3680, parseAmountCents("36.80"))
        assertEquals(3681, parseAmountCents("36.805"))
        assertNull(parseAmountCents("abc"))
    }

    @Test
    fun formatsCentsForTextInput() {
        assertEquals("36.80", formatAmountInput(3680))
        assertEquals("", formatAmountInput(null))
    }

    @Test
    fun displaysIsoTimeWithoutLeakingRawSeparatorInNormalCase() {
        val rendered = displayTime("2026-05-03T04:20:00Z")

        assertTrue(rendered.contains("2026-05-03"))
        assertTrue(rendered.contains(":"))
    }

    @Test
    fun updatesDateWithoutLosingExistingTime() {
        val selectedDateMillis = LocalDate.parse("2026-05-04")
            .atStartOfDay(ZoneOffset.UTC)
            .toInstant()
            .toEpochMilli()

        val iso = datePickerMillisToUtcIso(
            value = selectedDateMillis,
            currentIso = "2026-05-03T04:20:00Z",
            zoneId = ZoneOffset.UTC,
        )

        assertEquals("2026-05-04T04:20:00Z", iso)
    }

    @Test
    fun updatesTimeWithoutLosingExistingDate() {
        val iso = timePickerToUtcIso(
            hour = 8,
            minute = 45,
            currentIso = "2026-05-03T04:20:00Z",
            zoneId = ZoneOffset.UTC,
        )

        assertEquals("2026-05-03T08:45:00Z", iso)
        assertEquals(8, selectedHourFromIso(iso, ZoneOffset.UTC))
        assertEquals(45, selectedMinuteFromIso(iso, ZoneOffset.UTC))
    }

    @Test
    fun formatsStorageSize() {
        assertEquals("512 B", formatStorageSize(512))
        assertEquals("1 KB", formatStorageSize(1024))
        assertEquals("1 MB", formatStorageSize(1024 * 1024))
    }
}
