package com.ticketbox.ui.screens.settings

import com.ticketbox.domain.model.DashboardCard
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class DashboardCardsScreenModelsTest {
    @Test
    fun summaryCountsVisibleAndHiddenCards() {
        val summary = dashboardCardsSummary(
            listOf(
                dashboardCard("pending", visible = true),
                dashboardCard("reports", visible = false),
                dashboardCard("budget", visible = true),
            ),
        )

        assertEquals(3, summary.totalCount)
        assertEquals(2, summary.visibleCount)
        assertEquals(1, summary.hiddenCount)
        assertEquals("pending", summary.firstVisibleTitle)
    }

    @Test
    fun summaryHandlesAllHiddenCards() {
        val summary = dashboardCardsSummary(
            listOf(
                dashboardCard("pending", visible = false),
                dashboardCard("reports", visible = false),
            ),
        )

        assertEquals(2, summary.totalCount)
        assertEquals(0, summary.visibleCount)
        assertEquals(2, summary.hiddenCount)
        assertNull(summary.firstVisibleTitle)
    }

    private fun dashboardCard(key: String, visible: Boolean): DashboardCard =
        DashboardCard(key = key, title = key, visible = visible, position = 0)
}
