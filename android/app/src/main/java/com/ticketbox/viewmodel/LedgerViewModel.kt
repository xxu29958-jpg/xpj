package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.domain.model.CsvExport
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.filterConfirmedExpenses
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.time.YearMonth

data class LedgerUiState(
    val items: List<Expense> = emptyList(),
    val categories: List<String> = emptyList(),
    val months: List<String> = emptyList(),
    val exportFile: CsvExport? = null,
    val monthFilter: String = YearMonth.now().toString(),
    val categoryFilter: String = "",
    val query: String = "",
    val lastSyncAt: String? = null,
    val syncing: Boolean = false,
    val exporting: Boolean = false,
    val creatingManual: Boolean = false,
    val message: String? = null,
)

class LedgerViewModel(
    private val repository: ExpenseRepository,
) : ViewModel() {
    private val _uiState = MutableStateFlow(LedgerUiState(lastSyncAt = repository.lastConfirmedSyncAt()))
    val uiState: StateFlow<LedgerUiState> = _uiState.asStateFlow()
    private var allConfirmed: List<Expense> = emptyList()

    init {
        loadCategories()
        loadMonths()
        viewModelScope.launch {
            repository.observeConfirmed().collect { expenses ->
                allConfirmed = expenses
                _uiState.update { state -> state.copy(items = filterItems(expenses, state)) }
            }
        }
        sync()
    }

    private fun loadCategories() {
        viewModelScope.launch {
            repository.categories()
                .onSuccess { categories -> _uiState.update { it.copy(categories = categories) } }
        }
    }

    private fun loadMonths() {
        viewModelScope.launch {
            repository.months()
                .onSuccess { months -> _uiState.update { it.copy(months = months) } }
        }
    }

    private fun filterItems(expenses: List<Expense>, state: LedgerUiState): List<Expense> {
        return filterConfirmedExpenses(
            expenses = expenses,
            month = state.monthFilter,
            category = state.categoryFilter,
            query = state.query,
        )
    }

    fun setMonthFilter(value: String) {
        _uiState.update { state ->
            state.copy(monthFilter = value, items = filterItems(allConfirmed, state.copy(monthFilter = value)))
        }
    }

    fun setCategoryFilter(value: String) {
        _uiState.update { state ->
            state.copy(categoryFilter = value, items = filterItems(allConfirmed, state.copy(categoryFilter = value)))
        }
    }

    fun setQuery(value: String) {
        _uiState.update { state ->
            state.copy(query = value, items = filterItems(allConfirmed, state.copy(query = value)))
        }
    }

    fun clearFilters() {
        _uiState.update { state ->
            val next = state.copy(monthFilter = "", categoryFilter = "", query = "")
            next.copy(items = filterItems(allConfirmed, next))
        }
    }

    fun sync() {
        viewModelScope.launch {
            _uiState.update { it.copy(syncing = true, message = null) }
            val filters = _uiState.value
            repository.syncConfirmed(
                month = filters.monthFilter.trim().ifBlank { null },
                category = filters.categoryFilter.trim().ifBlank { null },
            )
                .onSuccess {
                    _uiState.update {
                        it.copy(
                            syncing = false,
                            lastSyncAt = repository.lastConfirmedSyncAt(),
                            message = "同步完成",
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(syncing = false, message = error.message ?: "暂时同步不了，先看本机账本。")
                    }
                }
        }
    }

    fun exportCsv() {
        viewModelScope.launch {
            val filters = _uiState.value
            if (filters.items.isEmpty()) {
                _uiState.update {
                    it.copy(message = "暂无可导出的已确认账单。请先确认几笔账单，或重新同步后再试。")
                }
                return@launch
            }
            _uiState.update { it.copy(exporting = true, message = null) }
            repository.exportConfirmedCsv(
                month = filters.monthFilter,
                category = filters.categoryFilter,
            )
                .onSuccess { exportFile ->
                    _uiState.update {
                        it.copy(exportFile = exportFile, exporting = false, message = "请选择保存位置")
                    }
                }
                .onFailure { error ->
                    _uiState.update { it.copy(exporting = false, message = error.message ?: "导出失败") }
                }
        }
    }

    fun createManualExpense(draft: ExpenseDraft) {
        viewModelScope.launch {
            if (draft.amountCents == null) {
                _uiState.update { it.copy(message = "请先填写金额。") }
                return@launch
            }
            _uiState.update { it.copy(creatingManual = true, message = null) }
            repository.createManualExpense(draft)
                .onSuccess { expense ->
                    loadCategories()
                    loadMonths()
                    _uiState.update { state ->
                        val next = state.copy(
                            creatingManual = false,
                            monthFilter = expense.expenseTime?.take(7) ?: state.monthFilter,
                            categoryFilter = "",
                            message = "已记入账本",
                        )
                        next.copy(items = filterItems(allConfirmed, next))
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(creatingManual = false, message = error.message ?: "保存失败")
                    }
                }
        }
    }

    fun exportLaunchHandled() {
        _uiState.update { it.copy(exportFile = null) }
    }

    fun exportFinished(message: String) {
        _uiState.update { it.copy(message = message) }
    }
}
