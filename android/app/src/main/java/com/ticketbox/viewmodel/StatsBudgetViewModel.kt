package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.BudgetActions
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.BudgetProgress
import com.ticketbox.domain.model.BudgetProgressStatus
import com.ticketbox.domain.model.toBudgetProgress
import com.ticketbox.domain.model.toBudgetProgressStatus
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import java.time.YearMonth

private data class StatsBudgetSnapshot(
    val progress: BudgetProgress?,
    val status: BudgetProgressStatus,
)

class StatsBudgetViewModel(private val budgetRepository: BudgetActions) : ViewModel() {
    private val _uiState = MutableStateFlow(StatsBudgetUiState())
    val uiState: StateFlow<StatsBudgetUiState> = _uiState.asStateFlow()
    private val budgetCache = mutableMapOf<String, StatsBudgetSnapshot>()
    private val inFlight = mutableMapOf<String, Long>()
    private var activeBinding: LogicalSessionBinding? = null
    private var selectedMonth: String? = null
    private var requestSequence = 0L

    init {
        viewModelScope.launch {
            budgetRepository.observeActiveLedgerAccess().map { it?.binding }.distinctUntilChanged().collect { binding ->
                activeBinding = binding
                budgetCache.clear()
                inFlight.clear()
                publish(selectedMonth.orEmpty())
                selectedMonth?.let { refresh(it) }
            }
        }
    }

    fun refresh(month: String, force: Boolean = false) {
        val requestedMonth = month.trim().ifBlank { YearMonth.now().toString() }
        selectedMonth = requestedMonth
        publish(requestedMonth)
        val binding = activeBinding ?: return
        if (!force && (requestedMonth in budgetCache || requestedMonth in inFlight)) return
        val request = ++requestSequence
        inFlight[requestedMonth] = request
        viewModelScope.launch {
            val result = budgetRepository.monthlyBudget(binding, requestedMonth)
            if (activeBinding != binding || inFlight[requestedMonth] != request) return@launch
            inFlight.remove(requestedMonth)
            result.onSuccess { budget ->
                budgetCache[requestedMonth] = StatsBudgetSnapshot(budget.toBudgetProgress(), budget.toBudgetProgressStatus())
                if (selectedMonth == requestedMonth) publish(requestedMonth)
            }
        }
    }

    private fun publish(month: String) {
        val cached = budgetCache[month]
        _uiState.value = StatsBudgetUiState(
            binding = activeBinding,
            budgetProgress = cached?.progress,
            budgetProgressStatus = cached?.status ?: BudgetProgressStatus.Unknown,
            month = month,
            ledgerId = activeBinding?.ledgerId,
        )
    }
}
