package com.ticketbox.ui.navigation

import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.ReportsOverview
import com.ticketbox.domain.model.CurrencyProjectionGap
import com.ticketbox.viewmodel.exportReport
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
    onRepair: (ReportRateContext) -> Unit,
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
        onMerchantCategoryChange = reports::setMerchantCategory,
        onExport = reports::exportReport,
        onRepairStatsRates = { gap ->
            val state = monthly.uiState.value
            val binding = state.binding
            if (binding != null && state.homeCurrencyCode == gap.homeCurrencyCode) {
                onRepair(ReportRateContext(binding, state.month, gap.homeCurrencyCode, gap.sourceCurrencyCode, gap.rateDate))
            }
        },
        onRepairRates = { gap ->
            val state = reports.uiState.value
            val binding = state.binding
            val report = state.reportsOverview
            if (binding != null && report != null && monthly.uiState.value.month == report.month) {
                onRepair(ReportRateContext(binding, report.month, report.homeCurrencyCode, gap?.sourceCurrencyCode, gap?.rateDate))
            }
        },
    ),
)
