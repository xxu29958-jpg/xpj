package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.RecurringRepository
import com.ticketbox.domain.model.BudgetProgress
import com.ticketbox.domain.model.DailySpend
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.CategoryInsight
import com.ticketbox.domain.model.LifestyleStats
import com.ticketbox.domain.model.MonthComparison
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.domain.model.RecurringCandidate
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.domain.model.DataQualitySummary
import com.ticketbox.domain.model.monthlyBudgetProgress
import com.ticketbox.domain.model.monthlyCategoryInsight
import com.ticketbox.domain.model.monthlyStatsFromConfirmedExpenses
import com.ticketbox.domain.model.monthlySpendingComparison
import com.ticketbox.domain.model.recentDailySpending
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
    val dataQuality: DataQualitySummary? = null,
    val months: List<String> = emptyList(),
    val month: String = YearMonth.now().toString(),
    val loading: Boolean = false,
    val message: String? = null,
)

class StatsViewModel(
    private val repository: ExpenseRepository,
    private val recurringRepository: RecurringRepository,
) : ViewModel() {
    private val _uiState = MutableStateFlow(StatsUiState())
    val uiState: StateFlow<StatsUiState> = _uiState.asStateFlow()
    private var confirmedCache: List<Expense> = emptyList()

    init {
        loadMonths()
        observeDailyTrend()
        refresh()
    }

    private fun loadMonths() {
        viewModelScope.launch {
            repository.months()
                .onSuccess { months -> _uiState.update { it.copy(months = months) } }
        }
    }

    private fun observeDailyTrend() {
        viewModelScope.launch {
            repository.observeConfirmed().collect { expenses ->
                confirmedCache = expenses
                _uiState.update {
                    val localStats = monthlyStatsFromConfirmedExpenses(expenses, it.month)
                    val visibleStats = it.stats ?: localStats
                    it.copy(
                        stats = visibleStats,
                        dailyTrend = recentDailySpending(expenses),
                        monthComparison = monthlySpendingComparison(expenses, it.month),
                        budgetProgress = monthlyBudgetProgress(visibleStats, repository.monthlyBudgetCents()),
                        categoryInsight = monthlyCategoryInsight(visibleStats),
                    )
                }
            }
        }
    }

    fun setMonth(value: String) {
        _uiState.update {
            val localStats = monthlyStatsFromConfirmedExpenses(confirmedCache, value)
            it.copy(
                month = value,
                stats = localStats,
                monthComparison = monthlySpendingComparison(confirmedCache, value),
                budgetProgress = monthlyBudgetProgress(localStats, repository.monthlyBudgetCents()),
                categoryInsight = monthlyCategoryInsight(localStats),
            )
        }
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, message = null) }
            val month = _uiState.value.month.trim().ifBlank { null }
            val budgetCents = repository.monthlyBudgetCents()
            // Fire-and-forget recurring reads; stats should remain usable if this section fails.
            launch {
                recurringRepository.items(includeArchived = false, month = month)
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
            repository.monthlyStats(month)
                .onSuccess { stats ->
                    repository.lifestyleStats(month)
                        .onSuccess { lifestyle ->
                            repository.syncConfirmed(month)
                            _uiState.update {
                                it.copy(
                                    stats = stats,
                                    lifestyleStats = lifestyle,
                                    budgetProgress = monthlyBudgetProgress(stats, budgetCents),
                                    categoryInsight = monthlyCategoryInsight(stats),
                                    loading = false,
                                )
                            }
                        }
                        .onFailure { error ->
                            _uiState.update {
                                it.copy(
                                    stats = stats,
                                    budgetProgress = monthlyBudgetProgress(stats, budgetCents),
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
                            monthlyStatsFromConfirmedExpenses(confirmedCache, value)
                        }
                        val visibleStats = fallbackStats ?: it.stats
                        it.copy(
                            stats = visibleStats,
                            budgetProgress = monthlyBudgetProgress(visibleStats, budgetCents),
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
}
