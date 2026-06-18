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
import com.ticketbox.domain.model.UiText
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
    val dashboardCardsMessage: UiText? = null,
    val reportsLoading: Boolean = false,
    val reportsMessage: UiText? = null,
    val dataQuality: DataQualitySummary? = null,
    val months: List<String> = emptyList(),
    val tags: List<String> = emptyList(),
    val month: String = YearMonth.now().toString(),
    val selectedTag: String = "",
    val loading: Boolean = false,
    val message: UiText? = null,
    /**
     * Monthly-stats **load failure** with no data to show at all (no backend stats,
     * no local-cache fallback). When set — and not [loading] — the screen renders a
     * retryable error state instead of the empty card, so a failed request stops
     * masquerading as "没有数据" (audit 8.4). Stays null when a local fallback exists
     * (that path uses [message] for the informational "本机估算" notice).
     */
    val statsLoadError: UiText? = null,
    /**
     * 轨道2 [P1]：pending 还款草稿数，统计页头「管理」菜单的「还款待确认」项据此显示计数 badge（>0 才显）。
     * 账本作用域（与月/标签无关），由 [StatsReportsViewModel] 在每次 refresh 时拉取、经 [mergeStatsUiState] 透传。
     */
    val pendingRepaymentDraftCount: Int = 0,
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
    val message: UiText? = null,
    val statsLoadError: UiText? = null,
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
    val dashboardCardsMessage: UiText? = null,
    val reportsLoading: Boolean = false,
    val reportsMessage: UiText? = null,
    val month: String = "",
    val selectedTag: String = "",
    // 轨道2 [P1]：pending 还款草稿数（菜单「还款待确认」badge 源）。账本作用域，不随月/标签 gate。
    val pendingRepaymentDraftCount: Int = 0,
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
        statsLoadError = monthly.statsLoadError,
        // 账本作用域 badge 计数：不随 reportsMatch/budgetMatch/标签 gate（与月/标签无关，标签筛选态也要显示）。
        pendingRepaymentDraftCount = reports.pendingRepaymentDraftCount,
    )
}
