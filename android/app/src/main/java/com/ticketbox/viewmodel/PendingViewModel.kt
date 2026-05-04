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
                .onFailure { error -> _uiState.update { it.copy(loading = false, message = error.message ?: "加载失败") } }
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
        viewModelScope.launch {
            repository.confirmExpense(expense.id)
                .onSuccess { confirmed ->
                    _uiState.update { state ->
                        state.copy(items = state.items.filterNot { it.id == confirmed.id }, message = "已确认入账")
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(message = error.message ?: "确认失败") } }
        }
    }

    fun reject(expense: Expense) {
        viewModelScope.launch {
            repository.rejectExpense(expense.id)
                .onSuccess { rejected ->
                    _uiState.update { state ->
                        state.copy(items = state.items.filterNot { it.id == rejected.id }, message = "已删除")
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(message = error.message ?: "删除失败") } }
        }
    }

    fun markNotDuplicate(expense: Expense) {
        viewModelScope.launch {
            repository.markNotDuplicate(expense.id)
                .onSuccess { updated ->
                    _uiState.update { state ->
                        state.copy(
                            items = state.items.map { if (it.id == updated.id) updated else it },
                            message = "已保留这条账单",
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(message = error.message ?: "操作失败") } }
        }
    }
}
