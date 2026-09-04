package com.ticketbox.ui.navigation

import com.ticketbox.ui.screens.StatsFilterActions
import com.ticketbox.ui.screens.StatsReportActions
import com.ticketbox.ui.screens.StatsScreenActions
import com.ticketbox.ui.screens.stats.OverviewInteractionActions
import com.ticketbox.viewmodel.MonthlyStatsViewModel
import com.ticketbox.viewmodel.StatsReportsViewModel

internal fun statsScreenActions(
    monthly: MonthlyStatsViewModel,
    reports: StatsReportsViewModel,
    shellState: MainShellState,
    month: String,
    overview: OverviewInteractionActions,
) = StatsScreenActions(
    filters = StatsFilterActions(
        onMonthChange = monthly::setMonth,
        onTagChange = monthly::setTag,
    ),
    onRefresh = { reloadAllStats(monthly, reports) },
    overview = overview,
    onOpenDataQuality = {
        shellState.openSecondaryPage(ProductSecondaryPage.InsightsDataQuality)
    },
    reports = StatsReportActions(
        onDrillToLedger = { category ->
            shellState.ledgerDrill.post(
                LedgerDrillRequest.Category(month = month, category = category),
            )
            shellState.openPrimaryDomainRoot(PrimaryDomain.Transactions)
        },
        onGranularityChange = reports::setGranularity,
        onRankingMetricChange = reports::setRankingMetric,
    ),
)
