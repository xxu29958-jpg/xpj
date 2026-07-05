package com.ticketbox.ui.screens

import com.ticketbox.R
import com.ticketbox.domain.model.DailySpend
import com.ticketbox.domain.model.LifestyleStats
import com.ticketbox.domain.model.MonthComparison
import com.ticketbox.domain.model.ReportGranularity
import com.ticketbox.domain.model.ReportRankingMetric
import com.ticketbox.domain.model.ReportsOverview
import com.ticketbox.domain.model.UiText
import com.ticketbox.viewmodel.StatsSource
import com.ticketbox.viewmodel.StatsUiState
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class StatsScreenRecentEvidenceTest {
    @Test
    fun overviewRecent7DaysAmountUsesBackendLifestyleValue() {
        val state = StatsUiState(
            statsSource = StatsSource.Backend,
            lifestyleStats = lifestyle(recent7DaysAmountCents = 8_800L),
            dailyTrend = listOf(DailySpend(date = "2026-07-01", label = "7/1", amountCents = 99_000L)),
        )

        assertEquals(8_800L, overviewRecent7DaysAmount(state))
    }

    @Test
    fun overviewRecent7DaysAmountDoesNotPromoteLocalTrendToBackendEvidence() {
        val state = StatsUiState(
            statsSource = StatsSource.LocalFallback,
            lifestyleStats = lifestyle(recent7DaysAmountCents = 8_800L),
            dailyTrend = listOf(
                DailySpend(date = "2026-07-01", label = "7/1", amountCents = 3_000L),
                DailySpend(date = "2026-07-02", label = "7/2", amountCents = 4_000L),
            ),
        )

        assertNull(overviewRecent7DaysAmount(state))
    }

    @Test
    fun overviewMonthComparisonUsesServerReportBaseline() {
        val localComparison = MonthComparison(
            currentMonth = "2026-07",
            previousMonth = "2026-06",
            currentAmountCents = 12_000L,
            previousAmountCents = 500L,
            deltaAmountCents = 11_500L,
            percentChange = 2300,
        )
        val state = StatsUiState(
            statsSource = StatsSource.Backend,
            month = "2026-07",
            monthComparison = localComparison,
            reportsOverview = reportsOverview(totalAmountCents = 12_000L, previousTotalAmountCents = 8_000L, previousCount = 2),
        )

        val comparison = overviewMonthComparison(state)

        requireNotNull(comparison)
        assertEquals("2026-07", comparison.currentMonth)
        assertEquals("2026-06", comparison.previousMonth)
        assertEquals(8_000L, comparison.previousAmountCents)
        assertEquals(4_000L, comparison.deltaAmountCents)
        assertEquals(50, comparison.percentChange)
    }

    @Test
    fun overviewMonthComparisonDoesNotPromoteLocalCacheComparison() {
        val state = StatsUiState(
            statsSource = StatsSource.Backend,
            month = "2026-07",
            monthComparison = MonthComparison(
                currentMonth = "2026-07",
                previousMonth = "2026-06",
                currentAmountCents = 12_000L,
                previousAmountCents = 8_000L,
                deltaAmountCents = 4_000L,
                percentChange = 50,
            ),
        )

        assertNull(overviewMonthComparison(state))
        assertNull(
            overviewMonthComparison(
                state.copy(
                    statsSource = StatsSource.LocalFallback,
                    reportsOverview = reportsOverview(totalAmountCents = 12_000L, previousTotalAmountCents = 8_000L, previousCount = 2),
                ),
            ),
        )
    }

    @Test
    fun overviewMonthComparisonRequiresReadablePreviousBaselineAndMatchingMonth() {
        val state = StatsUiState(
            statsSource = StatsSource.Backend,
            month = "2026-07",
        )

        assertNull(
            overviewMonthComparison(
                state.copy(reportsOverview = reportsOverview(totalAmountCents = 12_000L, previousTotalAmountCents = 0L, previousCount = 2)),
            ),
        )
        assertNull(
            overviewMonthComparison(
                state.copy(reportsOverview = reportsOverview(totalAmountCents = 12_000L, previousTotalAmountCents = 8_000L, previousCount = 0)),
            ),
        )
        assertNull(
            overviewMonthComparison(
                state.copy(reportsOverview = reportsOverview(month = "2026-06", totalAmountCents = 12_000L, previousTotalAmountCents = 8_000L, previousCount = 2)),
            ),
        )
    }

    @Test
    fun reportsUnavailableFallbackDoesNotPromoteLocalTrend() {
        val state = StatsUiState(
            dailyTrend = listOf(DailySpend(date = "2026-07-01", label = "7/1", amountCents = 99_000L)),
        )

        assertTrue(shouldShowReportsUnavailableFallback(state))
        assertFalse(shouldShowReportsUnavailableFallback(state.copy(reportsLoading = true)))
        assertFalse(shouldShowReportsUnavailableFallback(state.copy(selectedTag = "food")))
        assertFalse(shouldShowReportsUnavailableFallback(state.copy(reportsOverview = reportsOverview())))
    }

    @Test
    fun reportsTrendStatusMessageUsesUnavailableFallbackWhenOverviewIsMissing() {
        val message = UiText.res(R.string.stats_message_trend_failed)
        val state = StatsUiState(reportsMessage = message)

        assertTrue(shouldShowReportsUnavailableFallback(state))
        assertNull(reportsTrendStatusMessage(state))
    }

    @Test
    fun reportsTrendStatusMessageSurfacesPartialFailureWhenOverviewIsReadable() {
        val message = UiText.res(R.string.stats_message_reports_failed)
        val state = StatsUiState(
            reportsOverview = reportsOverview(),
            reportsMessage = message,
        )

        assertFalse(shouldShowReportsUnavailableFallback(state))
        assertEquals(message, reportsTrendStatusMessage(state))
    }

    private fun lifestyle(recent7DaysAmountCents: Long): LifestyleStats =
        LifestyleStats(
            month = "2026-07",
            aiSubscriptionAmountCents = 0L,
            digitalAmountCents = 0L,
            maxExpense = null,
            recent7DaysAmountCents = recent7DaysAmountCents,
            frequentMerchants = emptyList(),
        )

    private fun reportsOverview(
        month: String = "2026-07",
        totalAmountCents: Long = 0L,
        previousTotalAmountCents: Long = 0L,
        previousCount: Int = 0,
    ): ReportsOverview =
        ReportsOverview(
            month = month,
            timezone = "Asia/Shanghai",
            granularity = ReportGranularity.Day,
            totalAmountCents = totalAmountCents,
            count = 0,
            previousMonth = "2026-06",
            previousTotalAmountCents = previousTotalAmountCents,
            previousCount = previousCount,
            yearOverYearMonth = "2025-07",
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
