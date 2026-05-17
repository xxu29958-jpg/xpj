package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.LedgerActions
import com.ticketbox.domain.model.CsvExport
import com.ticketbox.domain.model.DEFAULT_EXPENSE_CATEGORIES
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.expenseLedgerMonth
import com.ticketbox.domain.model.filterConfirmedExpenses
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.time.YearMonth

enum class LedgerViewMode {
    Card,
    List,
    Table,
}

data class LedgerSummaryUi(
    val totalAmountCents: Long = 0L,
    val itemCount: Int = 0,
    val monthFilter: String = "",
    val syncing: Boolean = false,
    val lastSyncAt: String? = null,
    val readOnly: Boolean = false,
)

data class LedgerFilterUi(
    val monthFilter: String = "",
    val categoryFilter: String = "",
    val tagFilter: String = "",
    val query: String = "",
    val hasFilters: Boolean = false,
)

data class LedgerUiState(
    val items: List<Expense> = emptyList(),
    val categories: List<String> = DEFAULT_EXPENSE_CATEGORIES,
    val tags: List<String> = emptyList(),
    val months: List<String> = emptyList(),
    val readOnly: Boolean = false,
    val exportFile: CsvExport? = null,
    val monthFilter: String = YearMonth.now().toString(),
    val categoryFilter: String = "",
    val tagFilter: String = "",
    val query: String = "",
    val viewMode: LedgerViewMode = LedgerViewMode.Card,
    val lastSyncAt: String? = null,
    val syncing: Boolean = false,
    val exporting: Boolean = false,
    val creatingManual: Boolean = false,
    val message: String? = null,
) {
    val summary: LedgerSummaryUi
        get() = LedgerSummaryUi(
            totalAmountCents = items.sumOf { it.amountCents ?: 0L },
            itemCount = items.size,
            monthFilter = monthFilter,
            syncing = syncing,
            lastSyncAt = lastSyncAt,
            readOnly = readOnly,
        )

    val filter: LedgerFilterUi
        get() = LedgerFilterUi(
            monthFilter = monthFilter,
            categoryFilter = categoryFilter,
            tagFilter = tagFilter,
            query = query,
            hasFilters = monthFilter.isNotBlank() ||
                categoryFilter.isNotBlank() ||
                tagFilter.isNotBlank() ||
                query.isNotBlank(),
        )
}

class LedgerViewModel(
    private val repository: LedgerActions,
) : ViewModel() {
    private val _uiState = MutableStateFlow(
        LedgerUiState(
            readOnly = !repository.canModifyLedger(),
            lastSyncAt = repository.lastConfirmedSyncAt(),
        ),
    )
    val uiState: StateFlow<LedgerUiState> = _uiState.asStateFlow()
    private var allConfirmed: List<Expense> = emptyList()

    init {
        loadCategories()
        loadTags()
        loadMonths()
        viewModelScope.launch {
            repository.observeConfirmed().collect { expenses ->
                allConfirmed = expenses
                _uiState.update { state ->
                    state.copy(items = filterItems(expenses, state))
                }
            }
        }
        sync()
    }

    private fun loadCategories() {
        viewModelScope.launch {
            repository.categories()
                .onSuccess { categories -> _uiState.update { it.copy(categories = categories) } }
                .onFailure { _uiState.update { it.copy(categories = DEFAULT_EXPENSE_CATEGORIES) } }
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

    private fun filterItems(expenses: List<Expense>, state: LedgerUiState): List<Expense> {
        return filterConfirmedExpenses(
            expenses = expenses,
            month = state.monthFilter,
            category = state.categoryFilter,
            tag = state.tagFilter,
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

    fun setTagFilter(value: String) {
        _uiState.update { state ->
            state.copy(tagFilter = value, items = filterItems(allConfirmed, state.copy(tagFilter = value)))
        }
    }

    fun setQuery(value: String) {
        _uiState.update { state ->
            state.copy(query = value, items = filterItems(allConfirmed, state.copy(query = value)))
        }
    }

    fun setViewMode(value: LedgerViewMode) {
        _uiState.update { state -> state.copy(viewMode = value) }
    }

    fun clearFilters() {
        _uiState.update { state ->
            val next = state.copy(monthFilter = "", categoryFilter = "", tagFilter = "", query = "")
            next.copy(items = filterItems(allConfirmed, next))
        }
    }

    fun sync() {
        viewModelScope.launch {
            _uiState.update {
                it.copy(readOnly = !repository.canModifyLedger(), syncing = true, message = null)
            }
            val filters = _uiState.value
            repository.syncConfirmed(
                month = filters.monthFilter.trim().ifBlank { null },
                category = filters.categoryFilter.trim().ifBlank { null },
                tag = filters.tagFilter.trim().ifBlank { null },
            )
                .onSuccess {
                    _uiState.update {
                        it.copy(
                            syncing = false,
                            lastSyncAt = repository.lastConfirmedSyncAt(),
                            message = "更新完成",
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(syncing = false, message = error.message ?: "暂时更新不了，先看本机账本。")
                    }
                }
        }
    }

    fun exportCsv() {
        viewModelScope.launch {
            val filters = _uiState.value
            if (filters.items.isEmpty()) {
                _uiState.update {
                    it.copy(message = "暂无可导出的已确认账单。请先确认几笔账单，或重新更新后再试。")
                }
                return@launch
            }
            _uiState.update { it.copy(exporting = true, message = null) }
            repository.exportConfirmedCsv(
                month = filters.monthFilter,
                category = filters.categoryFilter,
                tag = filters.tagFilter,
            )
                .onSuccess { exportFile ->
                    _uiState.update {
                        it.copy(exportFile = exportFile, exporting = false, message = "请选择保存位置")
                    }
                }
                .onFailure { error ->
                    _uiState.update { it.copy(exporting = false, message = error.message ?: "没有导出成功，可以换个保存位置再试。") }
                }
        }
    }

    fun createManualExpense(draft: ExpenseDraft) {
        if (!repository.canModifyLedger()) {
            _uiState.update { it.copy(readOnly = true, creatingManual = false, message = READ_ONLY_LEDGER_MESSAGE) }
            return
        }
        viewModelScope.launch {
            if (draft.amountCents == null) {
                _uiState.update { it.copy(message = "请先填写金额。") }
                return@launch
            }
            _uiState.update { it.copy(creatingManual = true, message = null) }
            repository.createManualExpense(draft)
                .onSuccess { expense ->
                    loadCategories()
                    loadTags()
                    loadMonths()
                    _uiState.update { state ->
                        val next = state.copy(
                            creatingManual = false,
                            monthFilter = expenseLedgerMonth(expense) ?: state.monthFilter,
                            categoryFilter = "",
                            tagFilter = "",
                            message = "已记入账本",
                        )
                        next.copy(items = filterItems(allConfirmed, next))
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(creatingManual = false, message = error.message ?: "没有保存成功，请稍后再试。")
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
