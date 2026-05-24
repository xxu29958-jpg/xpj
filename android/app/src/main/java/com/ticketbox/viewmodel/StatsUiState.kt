package com.ticketbox.viewmodel

import com.ticketbox.domain.model.BudgetProgress
import com.ticketbox.domain.model.CategoryInsight
import com.ticketbox.domain.model.DailySpend
import com.ticketbox.domain.model.DashboardCard
import com.ticketbox.domain.model.DataQualitySummary
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.LifestyleStats
import com.ticketbox.domain.model.MonthComparison
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.domain.model.RecurringCandidate
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.domain.model.ReportsOverview
import java.time.YearMonth

/**
 * Whether [StatsUiState.stats] currently comes from the backend (authoritative)
 * or from the local Room cache (offline fallback). UI should be able to render
 * a "本机估算" indicator when this is [LocalFallback] — see
 * ENGINEERING_RULES §14 "数据真源" + audit P2-01.
 */
enum class StatsSource { None, Backend, LocalFallback }

data class StatsUiState(
    val stats: MonthlyStats? = null,
    val statsSource: StatsSource = StatsSource.None,
    val lifestyleStats: LifestyleStats? = null,
    val dailyTrend: List<DailySpend> = emptyList(),
    val monthComparison: MonthComparison? = null,
    val budgetProgress: BudgetProgress? = null,
    val categoryInsight: CategoryInsight? = null,
    val recurringItems: List<RecurringItem> = emptyList(),
    val recurringCandidates: List<RecurringCandidate> = emptyList(),
    val reportsOverview: ReportsOverview? = null,
    val reportGoals: List<Goal> = emptyList(),
    val lastUploadAt: String? = null,
    val dashboardCards: List<DashboardCard> = emptyList(),
    val dashboardCardsLoading: Boolean = false,
    val dashboardCardsMessage: String? = null,
    val reportsLoading: Boolean = false,
    val reportsMessage: String? = null,
    val dataQuality: DataQualitySummary? = null,
    val months: List<String> = emptyList(),
    val tags: List<String> = emptyList(),
    val month: String = YearMonth.now().toString(),
    val selectedTag: String = "",
    val loading: Boolean = false,
    val message: String? = null,
)

data class MonthlyStatsUiState(
    val stats: MonthlyStats? = null,
    val statsSource: StatsSource = StatsSource.None,
    val lifestyleStats: LifestyleStats? = null,
    val dailyTrend: List<DailySpend> = emptyList(),
    val monthComparison: MonthComparison? = null,
    val categoryInsight: CategoryInsight? = null,
    val recurringItems: List<RecurringItem> = emptyList(),
    val recurringCandidates: List<RecurringCandidate> = emptyList(),
    val lastUploadAt: String? = null,
    val dataQuality: DataQualitySummary? = null,
    val months: List<String> = emptyList(),
    val tags: List<String> = emptyList(),
    val month: String = YearMonth.now().toString(),
    val selectedTag: String = "",
    val loading: Boolean = false,
    val message: String? = null,
    val ledgerReady: Boolean = false,
    val activeLedgerId: String? = null,
)

data class StatsBudgetUiState(
    val budgetProgress: BudgetProgress? = null,
    val month: String = "",
    val ledgerId: String? = null,
)

data class StatsReportsUiState(
    val reportsOverview: ReportsOverview? = null,
    val reportGoals: List<Goal> = emptyList(),
    val dashboardCards: List<DashboardCard> = emptyList(),
    val dashboardCardsLoading: Boolean = false,
    val dashboardCardsMessage: String? = null,
    val reportsLoading: Boolean = false,
    val reportsMessage: String? = null,
    val month: String = "",
    val selectedTag: String = "",
)

internal fun mergeStatsUiState(
    monthly: MonthlyStatsUiState,
    budget: StatsBudgetUiState,
    reports: StatsReportsUiState,
): StatsUiState {
    val reportsMatch = reports.month == monthly.month &&
        reports.selectedTag == monthly.selectedTag.trim()
    val budgetMatch = budget.month == monthly.month &&
        budget.ledgerId == monthly.activeLedgerId
    return StatsUiState(
        stats = monthly.stats,
        statsSource = monthly.statsSource,
        lifestyleStats = monthly.lifestyleStats,
        dailyTrend = monthly.dailyTrend,
        monthComparison = monthly.monthComparison,
        budgetProgress = if (budgetMatch) budget.budgetProgress else null,
        categoryInsight = monthly.categoryInsight,
        recurringItems = monthly.recurringItems,
        recurringCandidates = monthly.recurringCandidates,
        reportsOverview = if (reportsMatch && monthly.selectedTag.isBlank()) reports.reportsOverview else null,
        reportGoals = if (reportsMatch && monthly.selectedTag.isBlank()) reports.reportGoals else emptyList(),
        lastUploadAt = monthly.lastUploadAt,
        dashboardCards = reports.dashboardCards,
        dashboardCardsLoading = reports.dashboardCardsLoading,
        dashboardCardsMessage = reports.dashboardCardsMessage,
        reportsLoading = if (reportsMatch) reports.reportsLoading else false,
        reportsMessage = if (reportsMatch) reports.reportsMessage else null,
        dataQuality = monthly.dataQuality,
        months = monthly.months,
        tags = monthly.tags,
        month = monthly.month,
        selectedTag = monthly.selectedTag,
        loading = monthly.loading,
        message = monthly.message,
    )
}
