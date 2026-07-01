package com.ticketbox.ui.screens.stats

import com.ticketbox.domain.model.DailySpend
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
            dailyTrend = listOf(
                DailySpend(date = "2026-07-01", label = "7/1", amountCents = 1_000L),
                DailySpend(date = "2026-07-02", label = "7/2", amountCents = 0L),
                DailySpend(date = "2026-07-03", label = "7/3", amountCents = 2_000L),
            ),
        )

        requireNotNull(model)
        assertEquals("work", model.tag)
        assertEquals("2026-07", model.month)
        assertEquals(12_345L, model.totalAmountCents)
        assertEquals(3, model.count)
        assertEquals(3_000L, model.recentAmountCents)
        assertEquals(2, model.recentActiveDayCount)
    }

    @Test
    fun tagScopeInsightModelDropsBlankTagAndClampsInvalidNumbers() {
        assertNull(
            tagScopeInsightModel(
                stats = MonthlyStats(
                    month = "2026-07",
                    totalAmountCents = 1L,
                    count = 1,
                    byCategory = emptyList(),
                ),
                selectedTag = " ",
                dailyTrend = emptyList(),
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
            dailyTrend = listOf(
                DailySpend(date = "2026-07-01", label = "7/1", amountCents = -500L),
                DailySpend(date = "2026-07-02", label = "7/2", amountCents = 900L),
            ),
        )

        requireNotNull(model)
        assertEquals(0L, model.totalAmountCents)
        assertEquals(0, model.count)
        assertEquals(900L, model.recentAmountCents)
        assertEquals(1, model.recentActiveDayCount)
    }
}
