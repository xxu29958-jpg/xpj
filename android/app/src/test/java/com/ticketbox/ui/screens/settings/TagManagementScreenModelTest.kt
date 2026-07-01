package com.ticketbox.ui.screens.settings

import com.ticketbox.domain.model.ManagedTag
import kotlin.test.Test
import kotlin.test.assertEquals

class TagManagementScreenModelTest {
    @Test
    fun summarySeparatesActiveAndUnusedTags() {
        val summary = tagManagementSummaryModel(
            listOf(
                tag("a", usage = 4),
                tag("b", usage = 0),
                tag("c", usage = 2),
            ),
        )

        assertEquals(
            TagManagementSummaryModel(
                totalCount = 3,
                activeCount = 2,
                unusedCount = 1,
                usageCount = 6,
            ),
            summary,
        )
    }

    @Test
    fun summaryDoesNotLetNegativeUsagePolluteCounts() {
        val summary = tagManagementSummaryModel(listOf(tag("a", usage = -3)))

        assertEquals(1, summary.totalCount)
        assertEquals(0, summary.activeCount)
        assertEquals(1, summary.unusedCount)
        assertEquals(0, summary.usageCount)
    }

    private fun tag(id: String, usage: Int): ManagedTag =
        ManagedTag(publicId = id, name = id, usageCount = usage, rowVersion = 1L)
}
