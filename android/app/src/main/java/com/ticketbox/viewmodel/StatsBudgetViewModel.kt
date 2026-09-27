package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.BudgetActions
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.ReadSnapshot
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.domain.model.BudgetMonthly
import com.ticketbox.domain.model.BudgetProgressStatus
import com.ticketbox.domain.model.toBudgetProgress
import com.ticketbox.domain.model.toBudgetProgressStatus
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.Job
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import java.time.YearMonth

class StatsBudgetViewModel(private val budgetRepository: BudgetActions) : ViewModel() {
    private val _uiState = MutableStateFlow(StatsBudgetUiState())
    val uiState: StateFlow<StatsBudgetUiState> = _uiState.asStateFlow()
    private val budgetCache = mutableMapOf<String, ReadSnapshot<BudgetMonthly>>()
    private val inFlight = mutableMapOf<String, Long>()
    private var activeBinding: LogicalSessionBinding? = null
    private var selectedMonth: String? = null
    private var requestSequence = 0L
    private var observationsJob: Job? = null

    init {
        viewModelScope.launch {
            budgetRepository.observeActiveLedgerAccess().map { it?.binding }.distinctUntilChanged().collect { binding ->
                activeBinding = binding
                budgetCache.clear()
                inFlight.clear()
                observationsJob?.cancel()
                binding?.let(::observeBudgetChanges)
                publish(selectedMonth.orEmpty())
                selectedMonth?.let { refresh(it) }
            }
        }
    }

    private fun observeBudgetChanges(binding: LogicalSessionBinding) {
        observationsJob = viewModelScope.launch {
            launch(start = CoroutineStart.UNDISPATCHED) {
                budgetRepository.observeReadAccessDenials().collect { denial ->
                    if (activeBinding == binding && denial.binding == binding) {
                        budgetCache.clear()
                        inFlight.clear()
                        publish(selectedMonth.orEmpty())
                    }
                }
            }
            var previousDone: Set<Long> = emptySet()
            budgetRepository.observeSaves(binding).collect { saves ->
                if (activeBinding != binding) return@collect
                val done = saves.filter { it.row.status == PendingMutationStatus.Done }
                val changed = done.filter { it.row.id !in previousDone }
                    .mapNotNull { save -> save.intent?.month?.let { it to save.receipt } }
                previousDone = done.map { it.row.id }.toSet()
                changed.forEach { (month, receipt) ->
                    if (budgetCache[month]?.value.isOlderThanAccepted(receipt)) budgetCache.remove(month)
                    inFlight.remove(month)
                }
                if (changed.isNotEmpty()) publish(selectedMonth.orEmpty())
                selectedMonth?.takeIf { month -> changed.any { it.first == month } }?.let { refresh(it, force = true) }
            }
        }
    }

    fun refresh(month: String, force: Boolean = false) {
        val requestedMonth = runCatching { YearMonth.parse(month.trim()).toString() }.getOrNull() ?: return
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
            result.onSuccess { read ->
                budgetCache[requestedMonth] = read
                if (selectedMonth == requestedMonth) publish(requestedMonth)
            }.onFailure { error ->
                if (error.isReadAccessDenied()) {
                    budgetCache.clear()
                    inFlight.clear()
                    publish(selectedMonth.orEmpty())
                }
            }
        }
    }

    private fun publish(month: String) {
        val cached = budgetCache[month]
        _uiState.value = StatsBudgetUiState(
            binding = activeBinding,
            budgetProgress = cached?.value?.toBudgetProgress(),
            budgetProgressStatus = cached?.value?.toBudgetProgressStatus() ?: BudgetProgressStatus.Unknown,
            fetchedAt = cached?.fetchedAt,
            fromCache = cached?.fromCache == true,
            month = month,
            ledgerId = activeBinding?.ledgerId,
        )
    }
}
