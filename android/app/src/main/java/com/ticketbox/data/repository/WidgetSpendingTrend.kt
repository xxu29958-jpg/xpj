package com.ticketbox.data.repository

import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ReportGranularity
import com.ticketbox.domain.model.ReportsOverview
import com.ticketbox.domain.model.ReportsOverviewQuery
import java.time.Clock
import java.time.LocalDate
import java.time.YearMonth
import java.time.ZoneId

internal data class WidgetTrendDay(val date: LocalDate, val amountMinor: Long?)
internal data class WidgetSpendingTrend(
    val currencyCode: String,
    val days: List<WidgetTrendDay>,
    val currentWeek: Long?,
    val previousWeek: Long?,
    val fetchedAt: String,
)

/** Only complete, authoritative daily projections are summed; absent/null days stay unknown. */
internal fun widgetSpendingTrend(reports: List<ReportsOverview>, today: LocalDate, fetchedAt: String): WidgetSpendingTrend {
    require(reports.isNotEmpty())
    val first = reports.first()
    require(CurrencyCode.fromStorageKeyOrNull(first.homeCurrencyCode) != null)
    require(reports.all { it.granularity == ReportGranularity.Day && it.homeCurrencyCode == first.homeCurrencyCode && it.timezone == first.timezone })
    val points = reports.flatMap { report -> report.trend.map { point ->
        val date = LocalDate.parse(point.bucket)
        require(YearMonth.from(date).toString() == report.month)
        date to point.amountCents
    } }
    require(points.distinctBy { it.first }.size == points.size)
    val byDay = points.toMap()
    val weekStart = today.minusDays((today.dayOfWeek.value - 1).toLong())
    fun total(start: LocalDate, end: LocalDate): Long? {
        var sum = 0L
        var day = start
        while (!day.isAfter(end)) {
            sum = Math.addExact(sum, byDay[day] ?: return null)
            day = day.plusDays(1)
        }
        return sum
    }
    return WidgetSpendingTrend(first.homeCurrencyCode,
        (6 downTo 0).map { today.minusDays(it.toLong()).let { day -> WidgetTrendDay(day, byDay[day]) } },
        total(weekStart, today), total(weekStart.minusWeeks(1), today.minusWeeks(1)), fetchedAt)
}

internal suspend fun readWidgetSpendingTrend(
    reports: ReportsActions,
    calendars: LedgerCalendarReader,
    binding: LogicalSessionBinding,
    clock: Clock = Clock.systemUTC(),
): Result<WidgetSpendingTrend> = runCatching {
    val calendar = requireNotNull(calendars.refreshedLedgerCalendar(binding).getOrThrow())
    val today = clock.instant().atZone(ZoneId.of(calendar.timezoneName)).toLocalDate()
    val start = today.minusDays((today.dayOfWeek.value - 1).toLong()).minusWeeks(1)
    val months = listOf(YearMonth.from(start), YearMonth.from(today)).distinct()
    val projections = months.map { month ->
        reports.reportsOverview(ReportsOverviewQuery(month = month.toString(), timezone = calendar.timezoneName), binding)
            .getOrThrow().also { require(it.timezone == calendar.timezoneName) }
    }
    check(calendars.currentBinding() == binding)
    widgetSpendingTrend(projections, today, clock.instant().toString())
}
