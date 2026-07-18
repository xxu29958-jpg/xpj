package com.ticketbox.ui.screens.stats

import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.design.statsTokensForSkin
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class StatsSpendTrendChartTest {
    @Test
    fun trendAxisLabelsAndSelectionMapOneToOneWithVisiblePoints() {
        val points = (1..7).map { index ->
            StatsSpendChartPoint(label = "6/$index", amountCents = index * 100L)
        }

        assertEquals(
            listOf("6/1", "6/2", "6/3", "6/4", "6/5", "6/6", "6/7"),
            trendAxisLabels(points),
        )
        assertEquals(6, defaultTrendPointIndex(points))
        assertEquals(0, trendPointIndexForTap(x = 0f, width = 350f, pointCount = points.size))
        assertEquals(3, trendPointIndexForTap(x = 175f, width = 350f, pointCount = points.size))
        assertEquals(6, trendPointIndexForTap(x = 349f, width = 350f, pointCount = points.size))
    }

    @Test
    fun trendAxisLabelsKeepEveryAggregatedWindowReadable() {
        val points = (1..7).map { index ->
            StatsSpendChartPoint(label = "6/${index * 3 - 2}\n6/${index * 3}", amountCents = index * 100L)
        }

        assertEquals(points.map { it.label }, trendAxisLabels(points))
    }

    @Test
    fun trendWindowCountUsesSemanticLabelWidthAcrossContentWidths() {
        val minimumLabelWidth = statsTokensForSkin(AppSkin.Default).chart.minimumRangeLabelWidth.value
        val availableWidths = listOf(
            minimumLabelWidth * 4f,
            minimumLabelWidth * 5f,
            minimumLabelWidth * 6f,
        )

        val windowCounts = availableWidths.map { availableWidth ->
            trendWindowCountForAvailableWidth(
                availableWidthDp = availableWidth,
                minimumLabelWidthDp = minimumLabelWidth,
                maxWindows = 7,
            )
        }

        assertEquals(listOf(4, 5, 6), windowCounts)
        availableWidths.zip(windowCounts).forEach { (width, count) ->
            assertTrue(width / count >= minimumLabelWidth)
        }
    }
}
