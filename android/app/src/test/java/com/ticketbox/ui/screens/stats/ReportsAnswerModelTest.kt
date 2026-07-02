package com.ticketbox.ui.screens.stats

import com.ticketbox.domain.model.ReportGranularity
import com.ticketbox.domain.model.ReportTrendPoint
import com.ticketbox.domain.model.ReportsOverview
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class ReportsAnswerModelTest {
    @Test
    fun answerModelKeepsBackendGranularityAndComputesMonthDelta() {
        val model = reportsAnswerModel(
            overview(
                granularity = ReportGranularity.Week,
                totalAmountCents = 12_000L,
                previousTotalAmountCents = 8_000L,
            ),
        )

        assertEquals(ReportGranularity.Week, model.granularity)
        assertEquals(4_000L, model.monthDeltaAmountCents)
        assertEquals(50, model.monthDeltaPercent)
    }

    @Test
    fun answerModelDoesNotInventPercentWhenPreviousMonthIsEmpty() {
        val model = reportsAnswerModel(
            overview(
                totalAmountCents = 12_000L,
                previousTotalAmountCents = 0L,
            ),
        )

        assertEquals(12_000L, model.monthDeltaAmountCents)
        assertNull(model.monthDeltaPercent)
    }

    @Test
    fun trendEvidenceUsesSparseModeForUpToThreeActiveBuckets() {
        val evidence = reportsTrendEvidence(
            listOf(
                ReportTrendChartPoint(x = 0, label = "6/1", amountCents = 0L, count = 0),
                ReportTrendChartPoint(x = 1, label = "6/2", amountCents = 1_000L, count = 1),
                ReportTrendChartPoint(x = 2, label = "6/3", amountCents = 2_000L, count = 1),
                ReportTrendChartPoint(x = 3, label = "6/4", amountCents = 1_500L, count = 1),
            ),
        )

        assertEquals(ReportsTrendMode.Sparse, evidence.mode)
        assertEquals(3, evidence.positiveBucketCount)
    }

    @Test
    fun trendEvidenceSeparatesDominantPeakFromReadableChart() {
        val dominant = reportsTrendEvidence(
            listOf(
                ReportTrendChartPoint(x = 0, label = "6/1", amountCents = 9_000L, count = 1),
                ReportTrendChartPoint(x = 1, label = "6/2", amountCents = 500L, count = 1),
                ReportTrendChartPoint(x = 2, label = "6/3", amountCents = 500L, count = 1),
                ReportTrendChartPoint(x = 3, label = "6/4", amountCents = 500L, count = 1),
            ),
        )
        val balanced = reportsTrendEvidence(
            listOf(
                ReportTrendChartPoint(x = 0, label = "6/1", amountCents = 4_000L, count = 1),
                ReportTrendChartPoint(x = 1, label = "6/2", amountCents = 3_000L, count = 1),
                ReportTrendChartPoint(x = 2, label = "6/3", amountCents = 2_000L, count = 1),
                ReportTrendChartPoint(x = 3, label = "6/4", amountCents = 1_000L, count = 1),
            ),
        )

        assertEquals(ReportsTrendMode.DominantPeak, dominant.mode)
        assertEquals(85, dominant.peakSharePercent)
        assertEquals(ReportsTrendMode.Chart, balanced.mode)
    }

    private fun overview(
        granularity: ReportGranularity = ReportGranularity.Day,
        totalAmountCents: Long = 0L,
        previousTotalAmountCents: Long = 0L,
    ) = ReportsOverview(
        month = "2026-06",
        timezone = "Asia/Shanghai",
        granularity = granularity,
        totalAmountCents = totalAmountCents,
        count = if (totalAmountCents > 0L) 3 else 0,
        previousMonth = "2026-05",
        previousTotalAmountCents = previousTotalAmountCents,
        previousCount = if (previousTotalAmountCents > 0L) 2 else 0,
        yearOverYearMonth = "2025-06",
        yearOverYearTotalAmountCents = 0L,
        yearOverYearCount = 0,
        yearOverYearDeltaAmountCents = totalAmountCents,
        yearOverYearDeltaCount = 0,
        merchantCategory = null,
        rankingMetric = com.ticketbox.domain.model.ReportRankingMetric.Count,
        trend = listOf(
            ReportTrendPoint(bucket = "2026-06-01", label = "6/1", amountCents = totalAmountCents, count = 1),
        ),
        merchantRanking = emptyList(),
        categoryComparison = emptyList(),
    )
}
