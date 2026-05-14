package com.ticketbox.ui.screens.stats

import com.ticketbox.domain.model.ReportTrendPoint
import kotlin.test.Test
import kotlin.test.assertEquals

class ReportsInsightCardsTest {
    @Test
    fun trendChartPointsKeepServerOrderAndClampInvalidValues() {
        val points = reportTrendChartPoints(
            listOf(
                ReportTrendPoint(
                    bucket = "2026-05-01",
                    label = "05-01",
                    amountCents = 1_250L,
                    count = 1,
                ),
                ReportTrendPoint(
                    bucket = "2026-05-02",
                    label = "",
                    amountCents = -300L,
                    count = -1,
                ),
            ),
        )

        assertEquals(
            listOf(
                ReportTrendChartPoint(x = 0, label = "05-01", amountCents = 1_250L, count = 1),
                ReportTrendChartPoint(x = 1, label = "05-02", amountCents = 0L, count = 0),
            ),
            points,
        )
    }

    @Test
    fun compactAmountLabelsUseCentsWithoutFloatingPointMath() {
        assertEquals("¥0", compactAmountCentsLabel(0L))
        assertEquals("¥9.9", compactAmountCentsLabel(990L))
        assertEquals("¥1.2k", compactAmountCentsLabel(123_400L))
        assertEquals("¥1.2万", compactAmountCentsLabel(1_234_000L))
        assertEquals("-¥1.2万", compactAmountCentsLabel(-1_234_000L))
    }
}
