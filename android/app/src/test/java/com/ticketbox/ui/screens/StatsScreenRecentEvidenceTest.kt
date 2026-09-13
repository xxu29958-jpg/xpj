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
    @Test fun reportUnknownAmountsCannotCreateAnOverviewMonthComparison() {
        val report = reportsOverview(totalAmountCents = 12000, previousTotalAmountCents = 8000, previousCount = 2)
        val state = StatsUiState(statsSource = StatsSource.Backend, month = report.month)
        assertNull(overviewMonthComparison(state.copy(reportsOverview = report.copy(totalAmountCents = null))))
        assertNull(overviewMonthComparison(state.copy(reportsOverview = report.copy(previousTotalAmountCents = null))))
    }

    @Test
    fun overviewRecent7DaysAmountUsesBackendLifestyleValue() {
        val state = StatsUiState(
            statsSource = StatsSource.Backend,
            lifestyleStats = lifestyle(recent7DaysAmountCents = 8_800L),
            month = "2026-07",
            stats = com.ticketbox.domain.model.MonthlyStats(homeCurrencyCode = "CNY", month = "2026-07", totalAmountCents = 10000, count = 2, byCategory = emptyList()),
        )

        assertEquals(8_800L, overviewRecent7DaysAmount(state))
    }

    @Test
    fun overviewRecentWindowRejectsAnotherMonthCurrencyAndUnknownAmount() {
        val current = lifestyle(8800)
        val state = StatsUiState(statsSource = StatsSource.Backend, month = "2026-07", lifestyleStats = current,
            stats = com.ticketbox.domain.model.MonthlyStats(homeCurrencyCode = "CNY", month = "2026-07", totalAmountCents = 10000, count = 2, byCategory = emptyList()))
        assertNull(overviewRecent7DaysAmount(state.copy(lifestyleStats = current.copy(month = "2026-06"))))
        assertNull(overviewRecent7DaysAmount(state.copy(lifestyleStats = current.copy(homeCurrencyCode = "JPY"))))
        assertNull(overviewRecent7DaysAmount(state.copy(lifestyleStats = current.copy(recent7DaysAmountCents = null))))
    }

    @Test
    fun overviewRecent7DaysAmountDoesNotPromoteSavedSnapshotToCurrentEvidence() {
        val state = StatsUiState(
            statsSource = StatsSource.CachedSnapshot,
            lifestyleStats = lifestyle(recent7DaysAmountCents = 8_800L),
            month = "2026-07",
            stats = com.ticketbox.domain.model.MonthlyStats(homeCurrencyCode = "CNY", month = "2026-07", totalAmountCents = 10000, count = 2, byCategory = emptyList()),
        )

        assertNull(overviewRecent7DaysAmount(state))
    }

    @Test
    fun overviewMonthComparisonUsesServerReportBaseline() {
        val state = StatsUiState(
            statsSource = StatsSource.Backend,
            month = "2026-07",
            reportsOverview = reportsOverview(totalAmountCents = 12_000L, previousTotalAmountCents = 8_000L, previousCount = 2),
        )

        val comparison = overviewMonthComparison(state)

        requireNotNull(comparison)
        assertEquals("2026-07", comparison.currentMonth)
        assertEquals("2026-06", comparison.previousMonth)
        assertEquals(8_000L, comparison.previousAmountCents)
        assertEquals(4_000L, comparison.deltaAmountCents)
        assertEquals(50L, comparison.percentChange)

        val aggregateBoundary = overviewMonthComparison(
            state.copy(
                reportsOverview = reportsOverview(
                    totalAmountCents = 9_007_199_254_740_991L,
                    previousTotalAmountCents = 1L,
                    previousCount = 1,
                ),
            ),
        )
        requireNotNull(aggregateBoundary)
        assertEquals(900_719_925_474_099_000L, aggregateBoundary.percentChange)
    }

    @Test
    fun overviewMonthComparisonRequiresServerReportComparison() {
        val state = StatsUiState(
            statsSource = StatsSource.Backend,
            month = "2026-07",
        )

        assertNull(overviewMonthComparison(state))
        assertNull(
            overviewMonthComparison(
                state.copy(
                    statsSource = StatsSource.CachedSnapshot,
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
    fun reportsUnavailableFallbackKeepsEmptyEvidenceSeparateFromLoading() {
        val state = StatsUiState(
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
        LifestyleStats(homeCurrencyCode = "CNY", month = "2026-07",
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
            homeCurrencyCode = "CNY",
)
}
