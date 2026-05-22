package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.BudgetActions
import com.ticketbox.data.repository.RecurringActions
import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.data.repository.StatsActions
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
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
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

private data class BudgetCacheKey(val ledgerId: String?, val month: String)

private data class StatsRefreshSnapshot(
    val generation: Long,
    val ledgerId: String?,
    val month: String,
    val selectedTag: String,
)

class StatsViewModel(
    private val repository: StatsActions,
    private val recurringRepository: RecurringActions,
    private val budgetRepository: BudgetActions? = null,
    private val reportsRepository: ReportsActions? = null,
) : ViewModel() {
    private val _uiState = MutableStateFlow(StatsUiState())
    val uiState: StateFlow<StatsUiState> = _uiState.asStateFlow()
    private var confirmedCache: List<Expense> = emptyList()
    private val budgetCache = mutableMapOf<BudgetCacheKey, BudgetProgress?>()
    private var activeLedgerId: String? = null
    private var refreshGeneration = 0L
    private var observedLedgerOnce = false

    init {
        observeLedgerChanges()
        observeDailyTrend()
    }

    private fun observeLedgerChanges() {
        viewModelScope.launch {
            repository.observeActiveLedgerId()
                .distinctUntilChanged()
                .collect { ledgerId ->
                    val normalizedLedgerId = ledgerId?.takeIf { it.isNotBlank() }
                    if (observedLedgerOnce && activeLedgerId == normalizedLedgerId) {
                        return@collect
                    }
                    observedLedgerOnce = true
                    activeLedgerId = normalizedLedgerId
                    refreshGeneration += 1
                    confirmedCache = emptyList()
                    budgetCache.clear()
                    _uiState.update {
                        it.copy(
                            stats = null,
                            statsSource = StatsSource.None,
                            lifestyleStats = null,
                            dailyTrend = emptyList(),
                            monthComparison = null,
                            budgetProgress = null,
                            categoryInsight = null,
                            recurringItems = emptyList(),
                            recurringCandidates = emptyList(),
                            reportsOverview = null,
                            reportGoals = emptyList(),
                            dashboardCardsLoading = false,
                            reportsLoading = false,
                            dataQuality = null,
                            message = null,
                        )
                    }
                    loadMonths()
                    loadTags()
                    refresh()
                }
        }
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
                    // Only flip the source flag if we're actually substituting a local fallback —
                    // when backend stats already populated `it.stats`, observeConfirmed() must not
                    // pretend the visible figure is authoritative just because Room is in sync.
                    val nextSource = when {
                        it.stats != null -> it.statsSource
                        visibleStats != null -> StatsSource.LocalFallback
                        else -> StatsSource.None
                    }
                    it.copy(
                        stats = visibleStats,
                        statsSource = nextSource,
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
                statsSource = if (localStats != null) StatsSource.LocalFallback else StatsSource.None,
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
            val snapshot = beginRefreshSnapshot()
            _uiState.update {
                it.copy(
                    loading = true,
                    message = null,
                    lastUploadAt = repository.lastUploadAt(),
                )
            }
            val month = snapshot.month.trim().ifBlank { null }
            val tag = snapshot.selectedTag.trim().ifBlank { null }
            val selectedMonth = month ?: YearMonth.now().toString()
            val shouldLoadReports = tag == null
            budgetRepository?.let { budgetRepo ->
                launch {
                    val result = budgetRepo.monthlyBudget(selectedMonth)
                    if (!snapshot.isCurrent()) return@launch
                    result.onSuccess { budget ->
                        budgetCache[BudgetCacheKey(snapshot.ledgerId, selectedMonth)] = budget.toBudgetProgress()
                        _uiState.update {
                            it.copy(budgetProgress = budgetProgressFor(it.month, it.stats))
                        }
                    }
                }
            }
            // Fire-and-forget recurring reads; stats should remain usable if this section fails.
            launch {
                val result = recurringRepository.items(status = null, includeArchived = false, month = month)
                if (!snapshot.isCurrent()) return@launch
                result.onSuccess { items ->
                    _uiState.update { it.copy(recurringItems = items) }
                }
            }
            launch {
                val result = recurringRepository.candidates()
                if (!snapshot.isCurrent()) return@launch
                result.onSuccess { items ->
                    _uiState.update { it.copy(recurringCandidates = items) }
                }
            }
            // Fire-and-forget data quality summary; failure is non-fatal.
            launch {
                val result = repository.dataQualitySummary()
                if (!snapshot.isCurrent()) return@launch
                result.onSuccess { summary ->
                    _uiState.update { it.copy(dataQuality = summary) }
                }
            }
            reportsRepository?.let { reportsRepo ->
                loadDashboardCards(reportsRepo, snapshot)
                if (shouldLoadReports) {
                    loadReports(reportsRepo, snapshot, selectedMonth)
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
            val statsResult = repository.monthlyStats(month = month, tag = tag)
            if (!snapshot.isCurrent()) return@launch
            statsResult
                .onSuccess { stats ->
                    val lifestyleResult = repository.lifestyleStats(month)
                    if (!snapshot.isCurrent()) return@launch
                    lifestyleResult
                        .onSuccess { lifestyle ->
                            repository.syncConfirmed(month = month, category = null, tag = tag)
                            if (!snapshot.isCurrent()) return@launch
                            _uiState.update {
                                it.copy(
                                    stats = stats,
                                    statsSource = StatsSource.Backend,
                                    lifestyleStats = lifestyle,
                                    budgetProgress = budgetProgressFor(stats.month, stats),
                                    categoryInsight = monthlyCategoryInsight(stats),
                                    loading = false,
                                )
                            }
                        }
                        .onFailure { error ->
                            if (!snapshot.isCurrent()) return@launch
                            _uiState.update {
                                it.copy(
                                    stats = stats,
                                    statsSource = StatsSource.Backend,
                                    budgetProgress = budgetProgressFor(stats.month, stats),
                                    categoryInsight = monthlyCategoryInsight(stats),
                                    loading = false,
                                    message = error.message ?: "生活统计暂时打不开，请稍后再试。",
                                )
                            }
                        }
                }
                .onFailure { error ->
                    if (!snapshot.isCurrent()) return@launch
                    _uiState.update {
                        val fallbackStats = month?.let { value ->
                            monthlyStatsFromConfirmedExpenses(confirmedCache, value, tag.orEmpty())
                        }
                        val visibleStats = fallbackStats ?: it.stats
                        val nextSource = when {
                            fallbackStats != null -> StatsSource.LocalFallback
                            visibleStats != null -> it.statsSource
                            else -> StatsSource.None
                        }
                        it.copy(
                            stats = visibleStats,
                            statsSource = nextSource,
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

    private fun beginRefreshSnapshot(): StatsRefreshSnapshot {
        val state = _uiState.value
        refreshGeneration += 1
        return StatsRefreshSnapshot(
            generation = refreshGeneration,
            ledgerId = activeLedgerId,
            month = state.month,
            selectedTag = state.selectedTag.trim(),
        )
    }

    private fun StatsRefreshSnapshot.isCurrent(): Boolean {
        val state = _uiState.value
        return generation == refreshGeneration &&
            ledgerId == activeLedgerId &&
            month == state.month &&
            selectedTag == state.selectedTag.trim()
    }

    private fun loadDashboardCards(reportsRepo: ReportsActions, snapshot: StatsRefreshSnapshot) {
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    dashboardCardsLoading = true,
                    dashboardCardsMessage = null,
                )
            }
            val result = reportsRepo.dashboardCards(DashboardSurface.Android)
            if (!snapshot.isCurrent()) return@launch
            result
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

    private fun loadReports(reportsRepo: ReportsActions, snapshot: StatsRefreshSnapshot, month: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(reportsLoading = true, reportsMessage = null) }
            val overviewResult = reportsRepo.reportsOverview(
                ReportsOverviewQuery(
                    month = month,
                    granularity = ReportGranularity.Day,
                ),
            )
            val goalsResult = reportsRepo.goals(month = month)
            if (!snapshot.isCurrent()) {
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
            val key = BudgetCacheKey(activeLedgerId, month)
            return if (budgetCache.containsKey(key)) budgetCache[key] else null
        }
        return monthlyBudgetProgress(stats, repository.monthlyBudgetCents())
    }
}
