package com.ticketbox.domain.model

import kotlin.test.Test
import kotlin.test.assertEquals

class DashboardCardsTest {
    @Test
    fun visibleDashboardCardKeysUseAndroidDefaultsWhenServerHasNoCards() {
        assertEquals(
            listOf(
                DASHBOARD_CARD_PENDING,
                DASHBOARD_CARD_MONTHLY_SPEND,
                DASHBOARD_CARD_REPORTS,
                DASHBOARD_CARD_BUDGET,
                DASHBOARD_CARD_GOALS,
                DASHBOARD_CARD_RECURRING,
                DASHBOARD_CARD_RECENT_UPLOADS,
            ),
            visibleDashboardCardKeys(emptyList()),
        )
    }

    @Test
    fun visibleDashboardCardKeysHonorSavedVisibilityAndPosition() {
        val cards = listOf(
            DashboardCard(DASHBOARD_CARD_GOALS, "目标", visible = true, position = 20),
            DashboardCard(DASHBOARD_CARD_REPORTS, "趋势报表", visible = false, position = 0),
            DashboardCard(DASHBOARD_CARD_PENDING, "待确认", visible = true, position = 10),
            DashboardCard(DASHBOARD_CARD_BUDGET, "预算", visible = true, position = 10),
        )

        assertEquals(
            listOf(
                DASHBOARD_CARD_PENDING,
                DASHBOARD_CARD_BUDGET,
                DASHBOARD_CARD_GOALS,
            ),
            visibleDashboardCardKeys(cards),
        )
    }

    @Test
    fun statsTabMappingKeepsUserVisibilityAndSavedOrder() {
        val visibleKeys = visibleDashboardCardKeys(
            listOf(
                DashboardCard(DASHBOARD_CARD_RECURRING, "recurring", visible = true, position = 0),
                DashboardCard(DASHBOARD_CARD_BUDGET, "budget", visible = true, position = 10),
                DashboardCard(DASHBOARD_CARD_REPORTS, "reports", visible = true, position = 20),
                DashboardCard(DASHBOARD_CARD_GOALS, "goals", visible = false, position = 30),
                DashboardCard(DASHBOARD_CARD_PENDING, "pending", visible = true, position = 40),
            ),
        )

        assertEquals(
            listOf(DASHBOARD_CARD_RECURRING, DASHBOARD_CARD_BUDGET),
            statsDashboardKeysForTab(StatsTab.Budget, visibleKeys),
        )
        assertEquals(
            listOf(DASHBOARD_CARD_REPORTS),
            statsDashboardKeysForTab(StatsTab.Trend, visibleKeys),
        )
        assertEquals(
            emptyList(),
            statsDashboardKeysForTab(StatsTab.Goals, visibleKeys),
        )
        assertEquals(
            listOf(DASHBOARD_CARD_PENDING),
            statsDashboardKeysForTab(StatsTab.Overview, visibleKeys),
        )
    }

    @Test
    fun statsTabMappingHidesGlobalCardsWhenTagFiltered() {
        val visibleKeys = visibleDashboardCardKeys(emptyList())

        assertEquals(
            listOf(DASHBOARD_CARD_MONTHLY_SPEND),
            statsDashboardKeysForTab(StatsTab.Overview, visibleKeys, tagFilterActive = true),
        )
        assertEquals(
            listOf(DASHBOARD_CARD_REPORTS),
            statsDashboardKeysForTab(StatsTab.Trend, visibleKeys, tagFilterActive = true),
        )
        assertEquals(
            listOf(DASHBOARD_CARD_REPORTS),
            statsDashboardKeysForTab(StatsTab.Category, visibleKeys, tagFilterActive = true),
        )
        assertEquals(
            emptyList(),
            statsDashboardKeysForTab(StatsTab.Budget, visibleKeys, tagFilterActive = true),
        )
        assertEquals(
            emptyList(),
            statsDashboardKeysForTab(StatsTab.Goals, visibleKeys, tagFilterActive = true),
        )
    }
}
