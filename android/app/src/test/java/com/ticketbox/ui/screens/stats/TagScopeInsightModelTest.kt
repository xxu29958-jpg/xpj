package com.ticketbox.ui.screens.stats

import com.ticketbox.domain.model.MonthlyStats
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class TagScopeInsightModelTest {
    @Test
    fun tagScopeInsightModelTrimsTagAndUsesAuthoritativeMonthlyStats() {
        val model = tagScopeInsightModel(
            stats = MonthlyStats(
                month = "2026-07",
                totalAmountCents = 12_345L,
                count = 3,
                byCategory = emptyList(),
            ),
            selectedTag = "  work  ",
        )

        requireNotNull(model)
        assertEquals("work", model.tag)
        assertEquals("2026-07", model.month)
        assertEquals(12_345L, model.totalAmountCents)
        assertEquals(3, model.count)
    }

    @Test
    fun tagScopeInsightModelDropsBlankTagAndClampsInvalidMonthlyStats() {
        assertNull(
            tagScopeInsightModel(
                stats = MonthlyStats(
                    month = "2026-07",
                    totalAmountCents = 1L,
                    count = 1,
                    byCategory = emptyList(),
                ),
                selectedTag = " ",
            ),
        )

        val model = tagScopeInsightModel(
            stats = MonthlyStats(
                month = "2026-07",
                totalAmountCents = -1L,
                count = -2,
                byCategory = emptyList(),
            ),
            selectedTag = "refund",
        )

        requireNotNull(model)
        assertEquals(0L, model.totalAmountCents)
        assertEquals(0, model.count)
    }
}
