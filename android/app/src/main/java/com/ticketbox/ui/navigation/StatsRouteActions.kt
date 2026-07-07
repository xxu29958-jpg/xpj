package com.ticketbox.ui.navigation

import com.ticketbox.ui.screens.StatsFilterActions
import com.ticketbox.ui.screens.StatsReportActions
import com.ticketbox.ui.screens.StatsScreenActions
import com.ticketbox.ui.screens.stats.StatsPlanningActions
import com.ticketbox.viewmodel.MonthlyStatsViewModel
import com.ticketbox.viewmodel.StatsReportsViewModel

internal fun statsScreenActions(
    monthly: MonthlyStatsViewModel,
    reports: StatsReportsViewModel,
    shellState: MainShellState,
    month: String,
) = StatsScreenActions(
    filters = StatsFilterActions(
        onMonthChange = monthly::setMonth,
        onTagChange = monthly::setTag,
    ),
    onRefresh = { reloadAllStats(monthly, reports) },
    planning = StatsPlanningActions(
        onOpenSpendingGoal = { shellState.openStatsSecondary(StatsSecondaryPage.SpendingGoal) },
        onOpenBudget = { shellState.openStatsSecondary(StatsSecondaryPage.Budget) },
        onOpenRecurring = { shellState.openStatsSecondary(StatsSecondaryPage.Recurring) },
        onOpenIncomePlans = { shellState.openStatsSecondary(StatsSecondaryPage.IncomePlans) },
        onOpenDebtGoals = { shellState.openStatsSecondary(StatsSecondaryPage.DebtGoals) },
    ),
    reports = StatsReportActions(
        onDrillToLedger = { category ->
            shellState.ledgerDrill.post(LedgerDrillRequest(month = month, category = category))
            shellState.selectBottomTab(BottomTab.Ledger.key)
        },
        onGranularityChange = reports::setGranularity,
        onRankingMetricChange = reports::setRankingMetric,
    ),
)
