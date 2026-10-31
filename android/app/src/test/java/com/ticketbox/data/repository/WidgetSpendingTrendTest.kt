package com.ticketbox.data.repository

import com.ticketbox.domain.model.ReportGranularity
import com.ticketbox.domain.model.ReportRankingMetric
import com.ticketbox.domain.model.ReportTrendPoint
import com.ticketbox.domain.model.ReportsOverview
import java.time.LocalDate
import java.time.YearMonth
import org.junit.Assert.*
import org.junit.Test

class WidgetSpendingTrendTest {
    @Test fun mondayAcrossMonthBoundaryComparesOnlyTheSameWeekday() {
        val trend = widgetSpendingTrend(listOf(report("2026-10"), report("2026-11", mapOf(2 to 500L))),
            LocalDate.parse("2026-11-02"), "2026-11-02T00:00:00Z")
        assertEquals(LocalDate.parse("2026-10-27"), trend.days.first().date)
        assertEquals(7, trend.days.size)
        assertEquals(500L, trend.currentWeek)
        assertEquals(100L, trend.previousWeek)
        assertEquals(1100L, trend.days.sumOf { requireNotNull(it.amountMinor) })
    }

    @Test fun refundsRetainTheirSign() {
        val trend = widgetSpendingTrend(listOf(report("2026-10"), report("2026-11", mapOf(2 to -200L))),
            LocalDate.parse("2026-11-02"), "now")
        assertEquals(-200L, trend.currentWeek)
        assertEquals(-200L, trend.days.last().amountMinor)
    }

    @Test fun missingDayAndMissingConversionRemainUnknown() {
        val november = report("2026-11", mapOf(1 to null)).let { it.copy(trend = it.trend.filterNot { point -> point.bucket == "2026-11-02" }) }
        val trend = widgetSpendingTrend(listOf(report("2026-10"), november), LocalDate.parse("2026-11-02"), "now")
        assertNull(trend.days[5].amountMinor)
        assertNull(trend.days[6].amountMinor)
        assertNull(trend.currentWeek)
        assertEquals(100L, trend.previousWeek)
    }

    @Test fun incompatibleCurrencyTimezoneAndDuplicateDaysAreRejected() {
        val october = report("2026-10")
        val november = report("2026-11")
        listOf(november.copy(homeCurrencyCode = "JPY"), november.copy(timezone = "Asia/Tokyo"),
            november.copy(trend = november.trend + november.trend.first())).forEach { invalid ->
            assertThrows(IllegalArgumentException::class.java) {
                widgetSpendingTrend(listOf(october, invalid), LocalDate.parse("2026-11-02"), "now")
            }
        }
    }

    @Test fun overflowCannotTurnLargeSpendingIntoNegativeSpending() {
        val november = report("2026-11", mapOf(2 to Long.MAX_VALUE, 3 to 1L))
        assertThrows(ArithmeticException::class.java) {
            widgetSpendingTrend(listOf(report("2026-10"), november), LocalDate.parse("2026-11-03"), "now")
        }
    }

    private fun report(month: String, overrides: Map<Int, Long?> = emptyMap()) = ReportsOverview(
        month, "UTC", ReportGranularity.Day, 100L, 1, "2026-09", 0L, 0,
        "2025-10", 0L, 0, 100L, 1, null, ReportRankingMetric.Count,
        (1..YearMonth.parse(month).lengthOfMonth()).map { day ->
            val date = YearMonth.parse(month).atDay(day).toString()
            ReportTrendPoint(date, date, if (overrides.containsKey(day)) overrides[day] else 100L, 1)
        }, emptyList(), emptyList(), "CNY",
    )
}
