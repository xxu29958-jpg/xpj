package com.ticketbox.ui.screens

import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.ui.components.DataAuthorityTone
import com.ticketbox.viewmodel.MonthlyStatsUiState
import com.ticketbox.viewmodel.PendingUiState
import com.ticketbox.viewmodel.StatsSource
import kotlin.test.Test
import kotlin.test.assertEquals

class TodayAuthorityToneTest {
    @Test
    fun backgroundPendingRefreshKeepsBackendTone() {
        val state = TodayScreenState(
            pending = PendingUiState(loading = true, hasLoadedOnce = true),
            monthly = MonthlyStatsUiState(stats = monthlyStats(), statsSource = StatsSource.Backend),
            ledgerName = "home",
            ledgerRole = null,
        )

        assertEquals(DataAuthorityTone.Backend, state.authorityTone)
    }

    @Test
    fun initialPendingRefreshKeepsRefreshingTone() {
        val state = TodayScreenState(
            pending = PendingUiState(loading = true, hasLoadedOnce = false),
            monthly = MonthlyStatsUiState(stats = monthlyStats(), statsSource = StatsSource.Backend),
            ledgerName = "home",
            ledgerRole = null,
        )

        assertEquals(DataAuthorityTone.Refreshing, state.authorityTone)
    }
}

private fun monthlyStats() = MonthlyStats(
    month = "2026-07",
    totalAmountCents = 1200L,
    count = 1,
    byCategory = emptyList(),
)
