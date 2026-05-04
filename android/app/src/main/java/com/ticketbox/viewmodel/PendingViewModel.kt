package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ProtectedImage
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class PendingUiState(
    val items: List<Expense> = emptyList(),
    val thumbnails: Map<Long, ProtectedImage> = emptyMap(),
    val actionInProgressIds: Set<Long> = emptySet(),
    val loading: Boolean = false,
    val message: String? = null,
)

class PendingViewModel(
    private val repository: ExpenseRepository,
) : ViewModel() {
    private val _uiState = MutableStateFlow(PendingUiState())
    val uiState: StateFlow<PendingUiState> = _uiState.asStateFlow()

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, message = null) }
            repository.fetchPending()
                .onSuccess { expenses ->
                    val ids = expenses.map { expense -> expense.id }.toSet()
                    _uiState.update {
                        it.copy(
                            items = expenses,
                            thumbnails = it.thumbnails.filterKeys { id -> id in ids },
                            loading = false,
                        )
                    }
                    loadThumbnails(expenses)
                }
                .onFailure { error -> _uiState.update { it.copy(loading = false, message = error.message ?: "暂时加载不了，请稍后再试。") } }
        }
    }

    private suspend fun loadThumbnails(expenses: List<Expense>) {
        expenses
            .filter { it.imagePath != null && !_uiState.value.thumbnails.containsKey(it.id) }
            .forEach { expense ->
                repository.fetchThumbnail(expense.id)
                    .onSuccess { image ->
                        _uiState.update { state ->
                            state.copy(thumbnails = state.thumbnails + (expense.id to image))
                        }
                    }
            }
    }

    fun confirm(expense: Expense) {
        if (expense.amountCents == null) {
            _uiState.update { it.copy(message = "请先填写金额。") }
            return
        }
        if (expense.id in _uiState.value.actionInProgressIds) return
        viewModelScope.launch {
            _uiState.update { it.copy(actionInProgressIds = it.actionInProgressIds + expense.id, message = null) }
            repository.confirmExpense(expense.id)
                .onSuccess { confirmed ->
                    _uiState.update { state ->
                        state.copy(
                            items = state.items.filterNot { it.id == confirmed.id },
                            thumbnails = state.thumbnails - confirmed.id,
                            actionInProgressIds = state.actionInProgressIds - confirmed.id,
                            message = "已确认入账",
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            actionInProgressIds = it.actionInProgressIds - expense.id,
                            message = error.message ?: "没有确认成功，请稍后再试。",
                        )
                    }
                }
        }
    }

    fun reject(expense: Expense) {
        if (expense.id in _uiState.value.actionInProgressIds) return
        viewModelScope.launch {
            _uiState.update { it.copy(actionInProgressIds = it.actionInProgressIds + expense.id, message = null) }
            repository.rejectExpense(expense.id)
                .onSuccess { rejected ->
                    _uiState.update { state ->
                        state.copy(
                            items = state.items.filterNot { it.id == rejected.id },
                            thumbnails = state.thumbnails - rejected.id,
                            actionInProgressIds = state.actionInProgressIds - rejected.id,
                            message = "已删除",
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            actionInProgressIds = it.actionInProgressIds - expense.id,
                            message = error.message ?: "没有删除成功，请稍后再试。",
                        )
                    }
                }
        }
    }

    fun markNotDuplicate(expense: Expense) {
        if (expense.id in _uiState.value.actionInProgressIds) return
        viewModelScope.launch {
            _uiState.update { it.copy(actionInProgressIds = it.actionInProgressIds + expense.id, message = null) }
            repository.markNotDuplicate(expense.id)
                .onSuccess { updated ->
                    _uiState.update { state ->
                        state.copy(
                            items = state.items.map { if (it.id == updated.id) updated else it },
                            actionInProgressIds = state.actionInProgressIds - updated.id,
                            message = "已保留这条账单",
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            actionInProgressIds = it.actionInProgressIds - expense.id,
                            message = error.message ?: "暂时没处理成功，请稍后再试。",
                        )
                    }
                }
        }
    }
}
