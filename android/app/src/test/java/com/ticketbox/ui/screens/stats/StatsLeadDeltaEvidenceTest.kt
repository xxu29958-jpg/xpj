package com.ticketbox.ui.screens.stats

import com.ticketbox.domain.model.MonthComparison
import com.ticketbox.domain.model.ReportGranularity
import com.ticketbox.domain.model.ReportRankingMetric
import com.ticketbox.domain.model.ReportsOverview
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class StatsLeadDeltaEvidenceTest {
    @Test
    fun serverReportRequiresPositivePreviousAmountBeforeShowingMonthDelta() {
        val evidence = monthDeltaEvidence(
            overview = overview(previousTotalAmountCents = 0L, previousCount = 2),
            comparison = null,
        )

        assertNull(evidence)
    }

    @Test
    fun localFallbackComparisonUsesPositivePreviousAmountAsBaseline() {
        val evidence = monthDeltaEvidence(
            overview = null,
            comparison = MonthComparison(
                currentMonth = "2026-06",
                previousMonth = "2026-05",
                currentAmountCents = 12_000L,
                previousAmountCents = 8_000L,
                deltaAmountCents = 4_000L,
                percentChange = 50,
            ),
        )

        requireNotNull(evidence)
        assertEquals(8_000L, evidence.previousAmountCents)
        assertEquals(4_000L, evidence.deltaAmountCents)
        assertEquals(50, evidence.percentChange)
    }

    private fun overview(
        previousTotalAmountCents: Long,
        previousCount: Int,
    ) = ReportsOverview(
        month = "2026-06",
        timezone = "Asia/Shanghai",
        granularity = ReportGranularity.Day,
        totalAmountCents = 12_000L,
        count = 3,
        previousMonth = "2026-05",
        previousTotalAmountCents = previousTotalAmountCents,
        previousCount = previousCount,
        yearOverYearMonth = "2025-06",
        yearOverYearTotalAmountCents = 0L,
        yearOverYearCount = 0,
        yearOverYearDeltaAmountCents = 0L,
        yearOverYearDeltaCount = 0,
        merchantCategory = null,
        rankingMetric = ReportRankingMetric.Count,
        trend = emptyList(),
        merchantRanking = emptyList(),
        categoryComparison = emptyList(),
    )
}
