package com.ticketbox.viewmodel

import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.CsvExport
import com.ticketbox.domain.model.BudgetProgress
import com.ticketbox.domain.model.BudgetProgressStatus
import com.ticketbox.domain.model.DataQualitySummary
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.LifestyleStats
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.domain.model.ReportsOverview
import com.ticketbox.domain.model.UiText
import java.time.YearMonth

/** CachedSnapshot is the original server read, explicitly stale after a failed refresh. */
enum class StatsSource { None, Backend, CachedSnapshot }

enum class ReportGoalsLoadState { Unknown, Loading, Loaded, Failed }

enum class StatsFilterOptionsLoadState { Unknown, Loading, Loaded, Failed }

enum class DataQualityLoadState { Unknown, Loading, Loaded, Failed }

data class StatsUiState(
    val stats: MonthlyStats? = null,
    val statsSource: StatsSource = StatsSource.None,
    val lifestyleStats: LifestyleStats? = null,
    val statsFetchedAt: String? = null,
    val lifestyleFetchedAt: String? = null,
    val lifestyleFromCache: Boolean = false,
    val budgetProgress: BudgetProgress? = null,
    val budgetProgressStatus: BudgetProgressStatus = BudgetProgressStatus.Unknown,
    val reportsExporting: Boolean = false,
    val reportsExportMessage: UiText? = null,
    val reportsOverview: ReportsOverview? = null,
    val reportGoals: List<Goal> = emptyList(),
    val reportGoalsFetchedAt: String? = null,
    val reportGoalsFromCache: Boolean = false,
    val reportGoalsLoadState: ReportGoalsLoadState = ReportGoalsLoadState.Unknown,
    val lastUploadAt: String? = null,
    val reportsLoading: Boolean = false,
    val reportsMessage: UiText? = null,
    val dataQuality: DataQualitySummary? = null,
    val dataQualityLoadState: DataQualityLoadState = DataQualityLoadState.Unknown,
    val dataQualityError: UiText? = null,
    val months: List<String> = emptyList(),
    val monthsLoadState: StatsFilterOptionsLoadState = StatsFilterOptionsLoadState.Unknown,
    val tags: List<String> = emptyList(),
    val tagsLoadState: StatsFilterOptionsLoadState = StatsFilterOptionsLoadState.Unknown,
    val month: String = YearMonth.now().toString(),
    val selectedTag: String = "",
    val loading: Boolean = false,
    val message: UiText? = null,
    /**
     * Monthly-stats **load failure** with no data to show at all (no backend stats,
     * no previously confirmed server snapshot). When set — and not [loading] — the screen renders a
     * retryable error state instead of the empty card, so a failed request stops
     * masquerading as "没有数据" (audit 8.4). Stays null when a cached server snapshot exists
     * (that path uses [message] for the informational "已保存快照" notice).
     */
    val statsLoadError: UiText? = null,
)

data class MonthlyStatsUiState(
    val binding: LogicalSessionBinding? = null,
    val homeCurrencyCode: String? = null,
    val timezone: String = java.util.TimeZone.getDefault().id,
    val stats: MonthlyStats? = null,
    val statsSource: StatsSource = StatsSource.None,
    val lifestyleStats: LifestyleStats? = null,
    val statsFetchedAt: String? = null,
    val lifestyleFetchedAt: String? = null,
    val lifestyleFromCache: Boolean = false,
    val lastUploadAt: String? = null,
    val dataQuality: DataQualitySummary? = null,
    val dataQualityLoadState: DataQualityLoadState = DataQualityLoadState.Unknown,
    val dataQualityError: UiText? = null,
    val months: List<String> = emptyList(),
    val monthsLoadState: StatsFilterOptionsLoadState = StatsFilterOptionsLoadState.Unknown,
    val tags: List<String> = emptyList(),
    val tagsLoadState: StatsFilterOptionsLoadState = StatsFilterOptionsLoadState.Unknown,
    val month: String = YearMonth.now().toString(),
    val selectedTag: String = "",
    val loading: Boolean = false,
    val message: UiText? = null,
    val statsLoadError: UiText? = null,
    val ledgerReady: Boolean = false,
    val primaryRefreshRevision: Long = 0L,
) {
    val activeLedgerId: String? get() = binding?.ledgerId
}

data class StatsBudgetUiState(
    val binding: LogicalSessionBinding? = null,
    val budgetProgress: BudgetProgress? = null,
    val budgetProgressStatus: BudgetProgressStatus = BudgetProgressStatus.Unknown,
    val month: String = "",
    val ledgerId: String? = null,
)

data class StatsReportsUiState(
    val binding: LogicalSessionBinding? = null,
    val exportFile: CsvExport? = null,
    val exportId: String? = null,
    val exportDestinationPending: Boolean = false,
    val exporting: Boolean = false,
    val exportMessage: UiText? = null,
    val reportsOverview: ReportsOverview? = null,
    val reportGoals: List<Goal> = emptyList(),
    val reportGoalsFetchedAt: String? = null,
    val reportGoalsFromCache: Boolean = false,
    val reportGoalsLoadState: ReportGoalsLoadState = ReportGoalsLoadState.Unknown,
    val reportsLoading: Boolean = false,
    val reportsMessage: UiText? = null,
    val month: String = "",
    val selectedTag: String = "",
)

internal fun mergeStatsUiState(
    monthly: MonthlyStatsUiState,
    budget: StatsBudgetUiState,
    reports: StatsReportsUiState,
): StatsUiState {
    val reportsMatch = reports.month == monthly.month &&
        reports.selectedTag == monthly.selectedTag.trim() && reports.binding == monthly.binding
    val showReportDetails = reportsMatch && monthly.selectedTag.isBlank()
    val budgetMatch = budget.month == monthly.month &&
        budget.binding == monthly.binding
    val goalReport = reports.takeIf { showReportDetails }
    return StatsUiState(
        stats = monthly.stats,
        statsSource = monthly.statsSource,
        lifestyleStats = monthly.lifestyleStats,
        statsFetchedAt = monthly.statsFetchedAt,
        lifestyleFetchedAt = monthly.lifestyleFetchedAt,
        lifestyleFromCache = monthly.lifestyleFromCache,
        budgetProgress = if (budgetMatch) budget.budgetProgress else null,
        budgetProgressStatus = if (budgetMatch) {
            budget.budgetProgressStatus
        } else {
            BudgetProgressStatus.Unknown
        },
        reportsExporting = reports.exporting,
        reportsExportMessage = if (reportsMatch) reports.exportMessage else null,
        reportsOverview = if (showReportDetails) reports.reportsOverview else null,
        reportGoals = goalReport?.reportGoals.orEmpty(),
        reportGoalsFetchedAt = goalReport?.reportGoalsFetchedAt,
        reportGoalsFromCache = goalReport?.reportGoalsFromCache == true,
        reportGoalsLoadState = if (showReportDetails) {
            reports.reportGoalsLoadState
        } else {
            ReportGoalsLoadState.Unknown
        },
        lastUploadAt = monthly.lastUploadAt,
        reportsLoading = if (reportsMatch) reports.reportsLoading else false,
        reportsMessage = if (reportsMatch) reports.reportsMessage else null,
        dataQuality = monthly.dataQuality,
        dataQualityLoadState = monthly.dataQualityLoadState,
        dataQualityError = monthly.dataQualityError,
        months = monthly.months,
        monthsLoadState = monthly.monthsLoadState,
        tags = monthly.tags,
        tagsLoadState = monthly.tagsLoadState,
        month = monthly.month,
        selectedTag = monthly.selectedTag,
        loading = monthly.loading,
        message = monthly.message,
        statsLoadError = monthly.statsLoadError,
    )
}
