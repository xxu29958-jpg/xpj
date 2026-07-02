package com.ticketbox.ui.screens.stats

import com.ticketbox.domain.model.DailySpend
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class ReportsRecentWindowSummaryTest {
    @Test
    fun recentWindowSummaryComparesRecentThreeAgainstPreviousThree() {
        val summary = summarizeReportsRecentWindow(
            listOf(
                spend("6/24", 100L),
                spend("6/25", 200L),
                spend("6/26", 300L),
                spend("6/27", 400L),
                spend("6/28", 500L),
                spend("6/29", 600L),
                spend("6/30", 700L),
            ),
        )

        requireNotNull(summary)
        assertEquals(2_800L, summary.totalAmountCents)
        assertEquals(900L, summary.previousThreeAmountCents)
        assertEquals(1_800L, summary.recentThreeAmountCents)
        assertEquals("6/30", summary.peakLabel)
        assertEquals(25, summary.peakSharePercent)
        assertEquals(false, summary.shouldUseSparseRows)
    }

    @Test
    fun recentWindowSummaryClampsNegativeAmountsAndReturnsNullWhenEmpty() {
        val summary = summarizeReportsRecentWindow(
            listOf(
                spend("6/24", -100L),
                spend("6/25", 0L),
                spend("6/26", 900L),
                spend("6/27", 0L),
            ),
        )

        requireNotNull(summary)
        assertEquals(900L, summary.totalAmountCents)
        assertEquals(0L, summary.previousThreeAmountCents)
        assertEquals(900L, summary.recentThreeAmountCents)
        assertEquals(1, summary.activeDayCount)
        assertEquals(true, summary.shouldUseSparseRows)
        assertNull(summarizeReportsRecentWindow(listOf(spend("6/24", -100L), spend("6/25", 0L))))
    }

    @Test
    fun sparseRowsCanBeSuppressedWhenMonthRowsAlreadyShowTheSameDays() {
        val summary = summarizeReportsRecentWindow(
            listOf(
                spend("6/24", 0L),
                spend("6/25", 0L),
                spend("6/26", 0L),
                spend("6/27", 0L),
                spend("6/28", 0L),
                spend("6/29", 100L),
                spend("6/30", 200L),
            ),
        )

        requireNotNull(summary)
        assertEquals(true, summary.shouldUseSparseRows)
        assertEquals(true, summary.shouldShowSparseRows(avoidRepeatedSparseRows = false))
        assertEquals(false, summary.shouldShowSparseRows(avoidRepeatedSparseRows = true))
    }

    private fun spend(label: String, amountCents: Long) = DailySpend(
        date = "2026-06-${label.substringAfter('/')}",
        label = label,
        amountCents = amountCents,
    )
}
