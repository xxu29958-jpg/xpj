package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.BudgetActions
import com.ticketbox.domain.model.BudgetAdviceResult
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.time.YearMonth

enum class BudgetAdviceLoadState {
    Idle,
    Loading,
    Empty,
    Ready,
    Failed,
}

data class BudgetAdviceUiState(
    val month: String = YearMonth.now().toString(),
    val loadState: BudgetAdviceLoadState = BudgetAdviceLoadState.Idle,
    val canRequest: Boolean = true,
    val result: BudgetAdviceResult? = null,
    val error: UiText? = null,
)

class BudgetAdviceViewModel(
    private val repository: BudgetActions,
    initialMonth: String = YearMonth.now().toString(),
) : ViewModel() {
    private val _state = MutableStateFlow(
        BudgetAdviceUiState(
            month = initialMonth,
            canRequest = repository.canModifyLedger(),
        ),
    )
    val uiState: StateFlow<BudgetAdviceUiState> = _state.asStateFlow()
    private var requestGeneration = 0

    init {
        observeLedgerChanges()
    }

    private fun observeLedgerChanges() {
        viewModelScope.launch {
            repository.observeActiveLedgerId()
                .distinctUntilChanged()
                .drop(1)
                .collect {
                    requestGeneration += 1
                    _state.update { current ->
                        current.copy(
                            loadState = BudgetAdviceLoadState.Idle,
                            canRequest = repository.canModifyLedger(),
                            result = null,
                            error = null,
                        )
                    }
                }
        }
    }

    fun requestAdvice() {
        if (_state.value.loadState == BudgetAdviceLoadState.Loading) return
        if (!repository.canModifyLedger()) {
            _state.update {
                it.copy(
                    canRequest = false,
                    loadState = BudgetAdviceLoadState.Idle,
                    result = null,
                    error = UiText.res(R.string.common_readonly_ledger),
                )
            }
            return
        }
        val month = _state.value.month
        val generation = requestGeneration
        viewModelScope.launch {
            _state.update {
                it.copy(
                    loadState = BudgetAdviceLoadState.Loading,
                    canRequest = true,
                    error = null,
                )
            }
            repository.requestBudgetAdvice(month)
                .onSuccess { result ->
                    _state.update {
                        if (generation != requestGeneration || month != it.month) return@update it
                        it.copy(
                            loadState = if (result.advice == null) {
                                BudgetAdviceLoadState.Empty
                            } else {
                                BudgetAdviceLoadState.Ready
                            },
                            canRequest = repository.canModifyLedger(),
                            result = result,
                            error = null,
                        )
                    }
                }
                .onFailure { error ->
                    _state.update {
                        if (generation != requestGeneration || month != it.month) return@update it
                        it.copy(
                            loadState = BudgetAdviceLoadState.Failed,
                            canRequest = repository.canModifyLedger(),
                            error = error.toUiText(R.string.budget_advice_load_failed),
                        )
                    }
                }
        }
    }
}
