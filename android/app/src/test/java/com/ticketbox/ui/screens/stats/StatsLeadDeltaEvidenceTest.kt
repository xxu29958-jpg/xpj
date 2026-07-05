package com.ticketbox.ui.screens.stats

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
            overview = overview(totalAmountCents = 12_000L, previousTotalAmountCents = 0L, previousCount = 2),
        )

        assertNull(evidence)
    }

    @Test
    fun missingServerReportDoesNotPromoteLocalComparisonToLeadConclusion() {
        val evidence = monthDeltaEvidence(
            overview = null,
        )

        assertNull(evidence)
    }

    @Test
    fun serverReportUsesItsOwnPreviousAmountAsBaseline() {
        val evidence = monthDeltaEvidence(
            overview = overview(totalAmountCents = 12_000L, previousTotalAmountCents = 8_000L, previousCount = 2),
        )

        requireNotNull(evidence)
        assertEquals(8_000L, evidence.previousAmountCents)
        assertEquals(4_000L, evidence.deltaAmountCents)
    }

    private fun overview(
        totalAmountCents: Long,
        previousTotalAmountCents: Long,
        previousCount: Int,
    ) = ReportsOverview(
        month = "2026-06",
        timezone = "Asia/Shanghai",
        granularity = ReportGranularity.Day,
        totalAmountCents = totalAmountCents,
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
