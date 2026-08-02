package com.ticketbox.ui.screens.stats

import com.ticketbox.domain.model.ReportGranularity
import com.ticketbox.domain.model.ReportTrendPoint
import com.ticketbox.domain.model.ReportsOverview
import java.time.LocalDate
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
        assertEquals(50L, model.monthDeltaPercent)
        val aggregateBoundary = reportsAnswerModel(
            overview(
                totalAmountCents = 9_007_199_254_740_991L,
                previousTotalAmountCents = 1L,
            ),
        )
        assertEquals(900_719_925_474_099_000L, aggregateBoundary.monthDeltaPercent)
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
        assertEquals(false, model.hasPreviousMonthComparison)
        assertEquals(false, model.hasYearOverYearComparison)
    }

    @Test
    fun answerModelRequiresPreviousMonthCountBeforeShowingComparison() {
        val model = reportsAnswerModel(
            overview(
                totalAmountCents = 12_000L,
                previousTotalAmountCents = 8_000L,
            ).copy(previousCount = 0),
        )

        assertEquals(false, model.hasPreviousMonthComparison)
        assertNull(model.monthDeltaPercent)
    }

    @Test
    fun answerModelRequiresPositiveYearOverYearBaselineBeforeShowingComparison() {
        val model = reportsAnswerModel(
            overview(totalAmountCents = 12_000L).copy(
                yearOverYearTotalAmountCents = 0L,
                yearOverYearCount = 2,
            ),
        )

        assertEquals(false, model.hasYearOverYearComparison)
        assertEquals(0L, model.yearOverYearDeltaAmountCents)
    }

    @Test
    fun answerModelShowsYearOverYearWhenBaselineHasAmount() {
        val model = reportsAnswerModel(
            overview(totalAmountCents = 12_000L).copy(
                yearOverYearTotalAmountCents = 8_000L,
                yearOverYearCount = 2,
                yearOverYearDeltaAmountCents = 4_000L,
            ),
        )

        assertEquals(true, model.hasYearOverYearComparison)
        assertEquals(4_000L, model.yearOverYearDeltaAmountCents)
    }

    @Test
    fun answerModelDropsFutureDayBucketsOnlyForCurrentMonthTrend() {
        val today = LocalDate.parse("2026-07-05")
        val currentMonthModel = reportsAnswerModel(
            overview(
                month = "2026-07",
                totalAmountCents = 2_270L,
                trend = listOf(
                    ReportTrendPoint(bucket = "2026-07-03", label = "07-03", amountCents = 580L, count = 1),
                    ReportTrendPoint(bucket = "2026-07-05", label = "07-05", amountCents = 1_690L, count = 1),
                    ReportTrendPoint(bucket = "2026-07-06", label = "07-06", amountCents = 0L, count = 0),
                    ReportTrendPoint(bucket = "2026-07-31", label = "07-31", amountCents = 0L, count = 0),
                ),
            ),
            today = today,
        )
        val historicalMonthModel = reportsAnswerModel(
            overview(
                month = "2026-06",
                totalAmountCents = 580L,
                trend = listOf(
                    ReportTrendPoint(bucket = "2026-06-29", label = "06-29", amountCents = 580L, count = 1),
                    ReportTrendPoint(bucket = "2026-06-30", label = "06-30", amountCents = 0L, count = 0),
                ),
            ),
            today = today,
        )

        assertEquals(listOf("07-03", "07-05"), currentMonthModel.trendPoints.map { it.label })
        assertEquals(listOf(0, 1), currentMonthModel.trendPoints.map { it.x })
        assertEquals(listOf("06-29", "06-30"), historicalMonthModel.trendPoints.map { it.label })
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
        month: String = "2026-06",
        granularity: ReportGranularity = ReportGranularity.Day,
        totalAmountCents: Long = 0L,
        previousTotalAmountCents: Long = 0L,
        trend: List<ReportTrendPoint> = listOf(
            ReportTrendPoint(bucket = "$month-01", label = "6/1", amountCents = totalAmountCents, count = 1),
        ),
    ) = ReportsOverview(
        month = month,
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
        trend = trend,
        merchantRanking = emptyList(),
        categoryComparison = emptyList(),
    )
}
