package com.ticketbox.ui.components

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

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
    fun formatsStorageSize() {
        assertEquals("512 B", formatStorageSize(512))
        assertEquals("1 KB", formatStorageSize(1024))
        assertEquals("1 MB", formatStorageSize(1024 * 1024))
    }
}
