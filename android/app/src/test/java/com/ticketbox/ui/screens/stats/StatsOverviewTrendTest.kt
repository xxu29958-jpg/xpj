package com.ticketbox.ui.screens.stats

import com.ticketbox.domain.model.ReportTrendPoint
import kotlin.test.Test
import kotlin.test.assertEquals

class StatsOverviewTrendTest {
    @Test
    fun overviewTrendUsesOnlyServerReportBuckets() {
        val points = heroSpendTrendPoints(
            listOf(
                ReportTrendPoint(bucket = "2026-05-01", label = "5/1", amountCents = 1_200L, count = 1),
                ReportTrendPoint(bucket = "2026-05-02", label = "", amountCents = -300L, count = 1),
                ReportTrendPoint(bucket = "", label = "", amountCents = 900L, count = 1),
            ),
        )

        assertEquals(
            listOf(
                StatsSpendChartPoint(label = "5/1", amountCents = 1_200L),
                StatsSpendChartPoint(label = "2026-05-02", amountCents = 0L),
            ),
            points,
        )
    }

    @Test
    fun overviewTrendDoesNotFabricateLocalFallbackPointsWhenReportIsMissing() {
        assertEquals(emptyList(), heroSpendTrendPoints(emptyList()))
    }
}
