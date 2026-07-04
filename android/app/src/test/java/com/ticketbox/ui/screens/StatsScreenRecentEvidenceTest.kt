package com.ticketbox.ui.screens

import com.ticketbox.domain.model.DailySpend
import com.ticketbox.domain.model.LifestyleStats
import com.ticketbox.viewmodel.StatsSource
import com.ticketbox.viewmodel.StatsUiState
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

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

    private fun lifestyle(recent7DaysAmountCents: Long): LifestyleStats =
        LifestyleStats(
            month = "2026-07",
            aiSubscriptionAmountCents = 0L,
            digitalAmountCents = 0L,
            maxExpense = null,
            recent7DaysAmountCents = recent7DaysAmountCents,
            frequentMerchants = emptyList(),
        )
}
