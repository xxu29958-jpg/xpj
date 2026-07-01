package com.ticketbox.ui.screens.settings

import kotlin.test.Test
import kotlin.test.assertEquals

class RecycleBinScreenModelTest {
    @Test
    fun summaryUsesServerShortWindowCountWithinVisibleItems() {
        assertEquals(
            RecycleBinSummaryModel(totalCount = 3, shortWindowCount = 2, longTermCount = 1),
            recycleBinSummaryModel(itemCount = 3, shortWindowCount = 2),
        )
        assertEquals(
            RecycleBinSummaryModel(totalCount = 3, shortWindowCount = 3, longTermCount = 0),
            recycleBinSummaryModel(itemCount = 3, shortWindowCount = 8),
        )
        assertEquals(
            RecycleBinSummaryModel(totalCount = 0, shortWindowCount = 0, longTermCount = 0),
            recycleBinSummaryModel(itemCount = -1, shortWindowCount = -2),
        )
    }
}
