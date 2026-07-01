package com.ticketbox.ui.screens.stats

import kotlin.test.Test
import kotlin.test.assertEquals

class StatsSpendTrendChartTest {
    @Test
    fun trendAxisLabelsCanShowEveryRecentDay() {
        val points = (1..7).map { index ->
            StatsSpendChartPoint(label = "6/$index", amountCents = index * 100L)
        }

        assertEquals(
            listOf("6/1", "6/2", "6/3", "6/4", "6/5", "6/6", "6/7"),
            trendAxisLabels(points, showAllLabels = true),
        )
    }

    @Test
    fun trendAxisLabelsKeepMonthlyChartSparse() {
        val points = (1..7).map { index ->
            StatsSpendChartPoint(label = "6/$index", amountCents = index * 100L)
        }

        assertEquals(listOf("6/1", "6/4", "6/7"), trendAxisLabels(points))
    }
}
