package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.UiText
import java.time.YearMonth
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class SpendingGoalsUiState(
    val canModify: Boolean,
    val month: String,
    val goals: List<Goal> = emptyList(),
    val isLoading: Boolean = true,
    val loadError: UiText? = null,
)

class SpendingGoalsViewModel(
    private val reports: ReportsActions,
    initialMonth: String = YearMonth.now().toString(),
) : ViewModel() {
    private val _state = MutableStateFlow(
        SpendingGoalsUiState(
            canModify = reports.canModifyLedger(),
            month = initialMonth.validGoalMonth(),
        ),
    )
    val state: StateFlow<SpendingGoalsUiState> = _state.asStateFlow()
    private var loadJob: Job? = null
    private var loadGeneration = 0L

    init {
        refresh()
    }

    fun refresh() {
        val requestedMonth = _state.value.month
        val generation = ++loadGeneration
        loadJob?.cancel()
        _state.update {
            it.copy(
                canModify = reports.canModifyLedger(),
                isLoading = true,
                loadError = null,
            )
        }
        loadJob = viewModelScope.launch {
            val result = reports.goals(month = requestedMonth, includeArchived = false)
            if (generation != loadGeneration || _state.value.month != requestedMonth) return@launch
            result.fold(
                onSuccess = { goals ->
                    _state.update {
                        it.copy(
                            goals = goals.filter { goal -> goal.isSpendingLimit && !goal.isArchived },
                            isLoading = false,
                            loadError = null,
                        )
                    }
                },
                onFailure = { error ->
                    _state.update {
                        it.copy(
                            isLoading = false,
                            loadError = error.toUiText(R.string.spending_goals_load_failed),
                        )
                    }
                },
            )
        }
    }

    fun previousMonth() {
        shiftMonth(-1)
    }

    fun nextMonth() {
        shiftMonth(1)
    }

    private fun shiftMonth(delta: Long) {
        _state.update {
            val nextMonth = YearMonth.parse(it.month).plusMonths(delta).toString()
            it.copy(month = nextMonth, goals = emptyList(), loadError = null)
        }
        refresh()
    }
}

private fun String.validGoalMonth(): String =
    runCatching { YearMonth.parse(trim()).toString() }.getOrDefault(YearMonth.now().toString())
