package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.BudgetActions
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.RecurringRepository
import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.domain.model.BudgetProgress
import com.ticketbox.domain.model.DailySpend
import com.ticketbox.domain.model.DashboardCard
import com.ticketbox.domain.model.DashboardSurface
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.CategoryInsight
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.LifestyleStats
import com.ticketbox.domain.model.MonthComparison
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.domain.model.ReportGranularity
import com.ticketbox.domain.model.ReportsOverview
import com.ticketbox.domain.model.ReportsOverviewQuery
import com.ticketbox.domain.model.RecurringCandidate
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.domain.model.DataQualitySummary
import com.ticketbox.domain.model.filterConfirmedExpenses
import com.ticketbox.domain.model.monthlyBudgetProgress
import com.ticketbox.domain.model.monthlyCategoryInsight
import com.ticketbox.domain.model.monthlyStatsFromConfirmedExpenses
import com.ticketbox.domain.model.monthlySpendingComparison
import com.ticketbox.domain.model.recentDailySpending
import com.ticketbox.domain.model.toBudgetProgress
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.time.YearMonth

data class StatsUiState(
    val stats: MonthlyStats? = null,
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

class StatsViewModel(
    private val repository: ExpenseRepository,
    private val recurringRepository: RecurringRepository,
    private val budgetRepository: BudgetActions? = null,
    private val reportsRepository: ReportsActions? = null,
) : ViewModel() {
    private val _uiState = MutableStateFlow(StatsUiState())
    val uiState: StateFlow<StatsUiState> = _uiState.asStateFlow()
    private var confirmedCache: List<Expense> = emptyList()
    private val budgetCache = mutableMapOf<String, BudgetProgress?>()

    init {
        loadMonths()
        loadTags()
        observeDailyTrend()
        refresh()
    }

    private fun loadMonths() {
        viewModelScope.launch {
            repository.months()
                .onSuccess { months -> _uiState.update { it.copy(months = months) } }
        }
    }

    private fun loadTags() {
        viewModelScope.launch {
            repository.tags()
                .onSuccess { tags -> _uiState.update { it.copy(tags = tags) } }
        }
    }

    private fun observeDailyTrend() {
        viewModelScope.launch {
            repository.observeConfirmed().collect { expenses ->
                confirmedCache = expenses
                _uiState.update {
                    val visibleExpenses = filterConfirmedExpenses(
                        expenses = expenses,
                        month = "",
                        category = "",
                        tag = it.selectedTag,
                    )
                    val localStats = monthlyStatsFromConfirmedExpenses(expenses, it.month, it.selectedTag)
                    val visibleStats = it.stats ?: localStats
                    it.copy(
                        stats = visibleStats,
                        dailyTrend = recentDailySpending(visibleExpenses),
                        monthComparison = monthlySpendingComparison(visibleExpenses, it.month),
                        budgetProgress = budgetProgressFor(it.month, visibleStats),
                        categoryInsight = monthlyCategoryInsight(visibleStats),
                    )
                }
            }
        }
    }

    fun setMonth(value: String) {
        _uiState.update {
            val visibleExpenses = filterConfirmedExpenses(
                expenses = confirmedCache,
                month = "",
                category = "",
                tag = it.selectedTag,
            )
            val localStats = monthlyStatsFromConfirmedExpenses(confirmedCache, value, it.selectedTag)
            it.copy(
                month = value,
                stats = localStats,
                dailyTrend = recentDailySpending(visibleExpenses),
                monthComparison = monthlySpendingComparison(visibleExpenses, value),
                budgetProgress = budgetProgressFor(value, localStats),
                categoryInsight = monthlyCategoryInsight(localStats),
                reportsOverview = null,
                reportGoals = emptyList(),
                reportsLoading = false,
                reportsMessage = null,
            )
        }
        refresh()
    }

    fun setTag(value: String) {
        val cleanTag = value.trim()
        _uiState.update {
            val visibleExpenses = filterConfirmedExpenses(
                expenses = confirmedCache,
                month = "",
                category = "",
                tag = cleanTag,
            )
            val localStats = monthlyStatsFromConfirmedExpenses(confirmedCache, it.month, cleanTag)
            it.copy(
                selectedTag = cleanTag,
                stats = localStats,
                dailyTrend = recentDailySpending(visibleExpenses),
                monthComparison = monthlySpendingComparison(visibleExpenses, it.month),
                budgetProgress = budgetProgressFor(it.month, localStats),
                categoryInsight = monthlyCategoryInsight(localStats),
                reportsOverview = if (cleanTag.isBlank()) it.reportsOverview else null,
                reportGoals = if (cleanTag.isBlank()) it.reportGoals else emptyList(),
                reportsLoading = if (cleanTag.isBlank()) it.reportsLoading else false,
                reportsMessage = if (cleanTag.isBlank()) it.reportsMessage else null,
            )
        }
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    loading = true,
                    message = null,
                    lastUploadAt = repository.lastUploadAt(),
                )
            }
            val month = _uiState.value.month.trim().ifBlank { null }
            val tag = _uiState.value.selectedTag.trim().ifBlank { null }
            val selectedMonth = month ?: YearMonth.now().toString()
            val shouldLoadReports = tag == null
            budgetRepository?.let { budgetRepo ->
                launch {
                    budgetRepo.monthlyBudget(selectedMonth)
                        .onSuccess { budget ->
                            budgetCache[selectedMonth] = budget.toBudgetProgress()
                            _uiState.update {
                                it.copy(budgetProgress = budgetProgressFor(it.month, it.stats))
                            }
                        }
                }
            }
            // Fire-and-forget recurring reads; stats should remain usable if this section fails.
            launch {
                recurringRepository.items(status = null, includeArchived = false, month = month)
                    .onSuccess { items ->
                        _uiState.update { it.copy(recurringItems = items) }
                    }
            }
            launch {
                recurringRepository.candidates()
                    .onSuccess { items ->
                        _uiState.update { it.copy(recurringCandidates = items) }
                    }
            }
            // Fire-and-forget data quality summary; failure is non-fatal.
            launch {
                repository.dataQualitySummary()
                    .onSuccess { summary ->
                        _uiState.update { it.copy(dataQuality = summary) }
                    }
            }
            reportsRepository?.let { reportsRepo ->
                loadDashboardCards(reportsRepo)
                if (shouldLoadReports) {
                    loadReports(reportsRepo, selectedMonth)
                } else {
                    _uiState.update {
                        it.copy(
                            reportsOverview = null,
                            reportGoals = emptyList(),
                            reportsLoading = false,
                            reportsMessage = null,
                        )
                    }
                }
            }
            repository.monthlyStats(month = month, tag = tag)
                .onSuccess { stats ->
                    repository.lifestyleStats(month)
                        .onSuccess { lifestyle ->
                            repository.syncConfirmed(month = month, category = null, tag = tag)
                            _uiState.update {
                                it.copy(
                                    stats = stats,
                                    lifestyleStats = lifestyle,
                                    budgetProgress = budgetProgressFor(stats.month, stats),
                                    categoryInsight = monthlyCategoryInsight(stats),
                                    loading = false,
                                )
                            }
                        }
                        .onFailure { error ->
                            _uiState.update {
                                it.copy(
                                    stats = stats,
                                    budgetProgress = budgetProgressFor(stats.month, stats),
                                    categoryInsight = monthlyCategoryInsight(stats),
                                    loading = false,
                                    message = error.message ?: "生活统计暂时打不开，请稍后再试。",
                                )
                            }
                        }
                }
                .onFailure { error ->
                    _uiState.update {
                        val fallbackStats = month?.let { value ->
                            monthlyStatsFromConfirmedExpenses(confirmedCache, value, tag.orEmpty())
                        }
                        val visibleStats = fallbackStats ?: it.stats
                        it.copy(
                            stats = visibleStats,
                            budgetProgress = budgetProgressFor(month ?: it.month, visibleStats),
                            categoryInsight = monthlyCategoryInsight(visibleStats),
                            loading = false,
                            message = if (fallbackStats != null) {
                                "已显示本机账本统计，联网后会自动更新。"
                            } else {
                                error.message ?: "统计暂时打不开，请稍后再试。"
                            },
                        )
                    }
                }
        }
    }

    private fun loadDashboardCards(reportsRepo: ReportsActions) {
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    dashboardCardsLoading = true,
                    dashboardCardsMessage = null,
                )
            }
            reportsRepo.dashboardCards(DashboardSurface.Android)
                .onSuccess { cards ->
                    _uiState.update {
                        it.copy(
                            dashboardCards = cards.items,
                            dashboardCardsLoading = false,
                            dashboardCardsMessage = null,
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            dashboardCardsLoading = false,
                            dashboardCardsMessage = error.message ?: "首页卡片设置暂时打不开，已显示默认顺序。",
                        )
                    }
                }
        }
    }

    private fun loadReports(reportsRepo: ReportsActions, month: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(reportsLoading = true, reportsMessage = null) }
            val overviewResult = reportsRepo.reportsOverview(
                ReportsOverviewQuery(
                    month = month,
                    granularity = ReportGranularity.Day,
                ),
            )
            val goalsResult = reportsRepo.goals(month = month)
            val currentState = _uiState.value
            if (currentState.month != month || currentState.selectedTag.isNotBlank()) {
                return@launch
            }
            _uiState.update {
                it.copy(
                    reportsOverview = overviewResult.getOrNull(),
                    reportGoals = goalsResult.getOrDefault(emptyList()),
                    reportsLoading = false,
                    reportsMessage = when {
                        overviewResult.isFailure && goalsResult.isFailure -> "动态图表暂时打不开，稍后再试。"
                        overviewResult.isFailure -> "趋势图暂时打不开，稍后再试。"
                        else -> null
                    },
                )
            }
        }
    }

    private fun budgetProgressFor(month: String, stats: MonthlyStats?): BudgetProgress? {
        if (budgetRepository != null) {
            return if (budgetCache.containsKey(month)) budgetCache[month] else null
        }
        return monthlyBudgetProgress(stats, repository.monthlyBudgetCents())
    }
}
