package com.ticketbox.ui.screens.pending

import kotlin.test.Test
import kotlin.test.assertEquals

class InboxSectionTest {
    @Test
    fun processingIsNotAFilterTab() {
        assertEquals(
            listOf(InboxSection.Pending, InboxSection.Duplicates),
            InboxSection.entries,
        )
    }
}
