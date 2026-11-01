package com.ticketbox.data.repository

import com.ticketbox.domain.model.MonthlyStats

/** Uses the same complete server projection and offline/read-access policy as Insights. */
internal suspend fun readWidgetMonthlySummary(
    stats: StatsActions,
    calendars: LedgerCalendarReader,
): Result<ReadSnapshot<MonthlyStats>> {
    val binding = stats.statsBinding() ?: return Result.failure(IllegalStateException("No active ledger"))
    val month = calendars.newTaskMonth(binding).getOrElse { return Result.failure(it) }
        ?: return Result.failure(IllegalStateException("Ledger calendar unavailable"))
    return stats.monthlyStats(StatsQuery(binding, month))
}
