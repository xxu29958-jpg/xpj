package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.BudgetActions
import com.ticketbox.data.repository.StatsActions
import com.ticketbox.domain.model.BudgetProgress
import com.ticketbox.domain.model.BudgetProgressStatus
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.domain.model.monthlyBudgetProgress
import com.ticketbox.domain.model.toBudgetProgress
import com.ticketbox.domain.model.toBudgetProgressStatus
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.time.YearMonth

private data class StatsBudgetCacheKey(val ledgerId: String?, val month: String)
private data class StatsBudgetSnapshot(
    val progress: BudgetProgress?,
    val status: BudgetProgressStatus,
)

class StatsBudgetViewModel(
    private val statsRepository: StatsActions,
    private val budgetRepository: BudgetActions? = null,
) : ViewModel() {
    private val _uiState = MutableStateFlow(StatsBudgetUiState())
    val uiState: StateFlow<StatsBudgetUiState> = _uiState.asStateFlow()
    private val budgetCache = mutableMapOf<StatsBudgetCacheKey, StatsBudgetSnapshot>()
    private val inFlight = mutableSetOf<StatsBudgetCacheKey>()
    private var activeLedgerId: String? = null
    private var selectedMonth: String = YearMonth.now().toString()
    private var requestGeneration = 0L

    init {
        observeLedgerChanges()
    }

    private fun observeLedgerChanges() {
        viewModelScope.launch {
            statsRepository.observeActiveLedgerId()
                .distinctUntilChanged()
                .collect { ledgerId ->
                    activeLedgerId = ledgerId?.takeIf { it.isNotBlank() }
                    budgetCache.clear()
                    inFlight.clear()
                    requestGeneration += 1
                    _uiState.update {
                        it.copy(
                            budgetProgress = null,
                            budgetProgressStatus = BudgetProgressStatus.Unknown,
                            ledgerId = activeLedgerId,
                        )
                    }
                }
        }
    }

    fun refresh(month: String, stats: MonthlyStats?, force: Boolean = false) {
        val requestedMonth = month.trim().ifBlank { YearMonth.now().toString() }
        selectedMonth = requestedMonth
        val budgetRepo = budgetRepository
        if (budgetRepo == null) {
            val budgetCents = statsRepository.monthlyBudgetCents()
            val progress = monthlyBudgetProgress(stats, budgetCents)
            _uiState.update {
                it.copy(
                    budgetProgress = progress,
                    budgetProgressStatus = localBudgetProgressStatus(budgetCents, progress),
                    month = requestedMonth,
                    ledgerId = activeLedgerId,
                )
            }
            return
        }

        val key = StatsBudgetCacheKey(activeLedgerId, requestedMonth)
        val cachedBudget = budgetCache[key]
        _uiState.update {
            it.copy(
                budgetProgress = cachedBudget?.progress,
                budgetProgressStatus = cachedBudget?.status ?: BudgetProgressStatus.Unknown,
                month = requestedMonth,
                ledgerId = activeLedgerId,
            )
        }
        if (!force && budgetCache.containsKey(key)) return
        if (!force && key in inFlight) return

        requestGeneration += 1
        val generation = requestGeneration
        inFlight += key
        viewModelScope.launch {
            val result = budgetRepo.monthlyBudget(requestedMonth)
            inFlight -= key
            if (!isCurrent(generation, key)) return@launch
            result.onSuccess { budget ->
                val progress = budget.toBudgetProgress()
                val snapshot = StatsBudgetSnapshot(
                    progress = progress,
                    status = budget.toBudgetProgressStatus(),
                )
                budgetCache[key] = snapshot
                _uiState.update {
                    it.copy(
                        budgetProgress = snapshot.progress,
                        budgetProgressStatus = snapshot.status,
                        month = requestedMonth,
                        ledgerId = activeLedgerId,
                    )
                }
            }
        }
    }

    private fun isCurrent(generation: Long, key: StatsBudgetCacheKey): Boolean {
        return generation == requestGeneration &&
            key.ledgerId == activeLedgerId &&
            key.month == selectedMonth
    }
}

private fun localBudgetProgressStatus(
    budgetCents: Long?,
    progress: BudgetProgress?,
): BudgetProgressStatus = when {
    progress != null -> BudgetProgressStatus.Progress
    budgetCents != null && budgetCents > 0L -> BudgetProgressStatus.ConfiguredWithoutProgress
    else -> BudgetProgressStatus.Unconfigured
}
