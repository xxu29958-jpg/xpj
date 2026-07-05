package com.ticketbox.ui.screens.stats

import com.ticketbox.domain.model.DailySpend
import com.ticketbox.domain.model.ReportGranularity
import com.ticketbox.domain.model.ReportRankingMetric
import com.ticketbox.domain.model.ReportTrendPoint
import com.ticketbox.domain.model.ReportsOverview
import java.time.LocalDate
import kotlin.test.Test
import kotlin.test.assertEquals

class ReportsRecentWindowTrendTest {
    @Test
    fun recentWindowTrendUsesServerDayBucketsAndClampsInvalidAmounts() {
        val trend = reportsRecentWindowTrend(
            overview(
                granularity = ReportGranularity.Day,
                trend = listOf(
                    ReportTrendPoint(bucket = "2026-05-01", label = "5/1", amountCents = 1_250L, count = 1),
                    ReportTrendPoint(bucket = "2026-05-02", label = "", amountCents = -300L, count = 1),
                ),
            ),
        )

        assertEquals(
            listOf(
                DailySpend(date = "2026-05-01", label = "5/1", amountCents = 1_250L),
                DailySpend(date = "2026-05-02", label = "05-02", amountCents = 0L),
            ),
            trend,
        )
    }

    @Test
    fun recentWindowTrendDoesNotUseWeeklyReportBucketsAsDailyWindow() {
        val trend = reportsRecentWindowTrend(
            overview(
                granularity = ReportGranularity.Week,
                trend = listOf(
                    ReportTrendPoint(bucket = "2026-W20", label = "week 20", amountCents = 8_000L, count = 3),
                ),
            ),
        )

        assertEquals(emptyList(), trend)
    }

    @Test
    fun recentWindowTrendDropsFutureBucketsForCurrentMonthOnly() {
        val currentMonthTrend = reportsRecentWindowTrend(
            overview(
                month = "2026-07",
                granularity = ReportGranularity.Day,
                trend = listOf(
                    ReportTrendPoint(bucket = "2026-07-03", label = "07-03", amountCents = 580L, count = 1),
                    ReportTrendPoint(bucket = "2026-07-05", label = "07-05", amountCents = 1_690L, count = 1),
                    ReportTrendPoint(bucket = "2026-07-06", label = "07-06", amountCents = 0L, count = 0),
                    ReportTrendPoint(bucket = "2026-07-31", label = "07-31", amountCents = 0L, count = 0),
                ),
            ),
            today = LocalDate.parse("2026-07-05"),
        )
        val historicalMonthTrend = reportsRecentWindowTrend(
            overview(
                month = "2026-06",
                granularity = ReportGranularity.Day,
                trend = listOf(
                    ReportTrendPoint(bucket = "2026-06-29", label = "06-29", amountCents = 580L, count = 1),
                    ReportTrendPoint(bucket = "2026-06-30", label = "06-30", amountCents = 0L, count = 0),
                ),
            ),
            today = LocalDate.parse("2026-07-05"),
        )

        assertEquals(
            listOf(
                DailySpend(date = "2026-07-03", label = "07-03", amountCents = 580L),
                DailySpend(date = "2026-07-05", label = "07-05", amountCents = 1_690L),
            ),
            currentMonthTrend,
        )
        assertEquals(
            listOf(
                DailySpend(date = "2026-06-29", label = "06-29", amountCents = 580L),
                DailySpend(date = "2026-06-30", label = "06-30", amountCents = 0L),
            ),
            historicalMonthTrend,
        )
    }

    private fun overview(
        month: String = "2026-05",
        granularity: ReportGranularity,
        trend: List<ReportTrendPoint>,
    ) = ReportsOverview(
        month = month,
        timezone = "Asia/Shanghai",
        granularity = granularity,
        totalAmountCents = trend.sumOf { it.amountCents.coerceAtLeast(0L) },
        count = trend.sumOf { it.count.coerceAtLeast(0) },
        previousMonth = "2026-04",
        previousTotalAmountCents = 0L,
        previousCount = 0,
        yearOverYearMonth = "2025-05",
        yearOverYearTotalAmountCents = 0L,
        yearOverYearCount = 0,
        yearOverYearDeltaAmountCents = 0L,
        yearOverYearDeltaCount = 0,
        merchantCategory = null,
        rankingMetric = ReportRankingMetric.Count,
        trend = trend,
        merchantRanking = emptyList(),
        categoryComparison = emptyList(),
    )
}
