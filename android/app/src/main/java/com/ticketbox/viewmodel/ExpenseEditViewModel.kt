package com.ticketbox.viewmodel

import android.util.Log
import com.ticketbox.BuildConfig
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.domain.model.DEFAULT_EXPENSE_CATEGORIES
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.ExpenseSplits
import com.ticketbox.domain.model.ProtectedImage
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class ExpenseEditUiState(
    val expense: Expense? = null,
    val thumbnail: ProtectedImage? = null,
    val fullImage: ProtectedImage? = null,
    val categories: List<String> = DEFAULT_EXPENSE_CATEGORIES,
    val expenseItems: ExpenseItems? = null,
    val expenseSplits: ExpenseSplits? = null,
    val readOnly: Boolean = false,
    val imageLoading: Boolean = false,
    val itemsLoading: Boolean = false,
    val splitsLoading: Boolean = false,
    val ocrRunning: Boolean = false,
    val saving: Boolean = false,
    val itemsMessage: String? = null,
    val splitsMessage: String? = null,
    val message: String? = null,
    val done: Boolean = false,
)

class ExpenseEditViewModel(
    private val expenseId: Long,
    private val repository: ExpenseRepository,
) : ViewModel() {
    private companion object {
        const val IMAGE_LOG_TAG = "TicketboxImage"
    }

    private val _uiState = MutableStateFlow(
        ExpenseEditUiState(readOnly = !repository.canModifyLedger()),
    )
    val uiState: StateFlow<ExpenseEditUiState> = _uiState.asStateFlow()

    init {
        loadCategories()
        loadThumbnail()
        loadExpenseItems()
        loadExpenseSplits()
    }

    private fun loadCategories() {
        viewModelScope.launch {
            repository.categories()
                .onSuccess { categories -> _uiState.update { it.copy(categories = categories) } }
                .onFailure { _uiState.update { it.copy(categories = DEFAULT_EXPENSE_CATEGORIES) } }
        }
    }

    private fun loadThumbnail() {
        viewModelScope.launch {
            _uiState.update { it.copy(imageLoading = true) }
            repository.fetchThumbnail(expenseId)
                .onSuccess { image -> _uiState.update { it.copy(thumbnail = image, imageLoading = false) } }
                .onFailure { thumbnailError ->
                    if (BuildConfig.DEBUG) {
                        Log.w(IMAGE_LOG_TAG, "Thumbnail preview failed for expense=$expenseId: ${thumbnailError.message}")
                    }
                    repository.fetchImage(expenseId)
                        .onSuccess { image ->
                            _uiState.update { it.copy(fullImage = image, imageLoading = false) }
                        }
                        .onFailure { imageError ->
                            if (BuildConfig.DEBUG) {
                                Log.w(IMAGE_LOG_TAG, "Full image fallback failed for expense=$expenseId: ${imageError.message}")
                            }
                            _uiState.update { it.copy(imageLoading = false) }
                        }
                }
        }
    }

    private fun loadExpenseItems() {
        viewModelScope.launch {
            _uiState.update { it.copy(itemsLoading = true, itemsMessage = null) }
            repository.fetchExpenseItems(expenseId)
                .onSuccess { items ->
                    _uiState.update { it.copy(expenseItems = items, itemsLoading = false) }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            itemsLoading = false,
                            itemsMessage = error.message ?: "小票明细暂时加载失败。",
                        )
                    }
                }
        }
    }

    private fun loadExpenseSplits() {
        viewModelScope.launch {
            _uiState.update { it.copy(splitsLoading = true, splitsMessage = null) }
            repository.fetchExpenseSplits(expenseId)
                .onSuccess { splits ->
                    _uiState.update { it.copy(expenseSplits = splits, splitsLoading = false) }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            splitsLoading = false,
                            splitsMessage = error.message ?: "家庭拆账暂时加载失败。",
                        )
                    }
                }
        }
    }

    fun loadFullImage() {
        viewModelScope.launch {
            _uiState.update { it.copy(imageLoading = true, message = null) }
            repository.fetchImage(expenseId)
                .onSuccess { image -> _uiState.update { it.copy(fullImage = image, imageLoading = false) } }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            imageLoading = false,
                            message = error.message ?: "截图暂时打不开，请稍后再试。",
                        )
                    }
                }
        }
    }

    fun save(draft: ExpenseDraft) {
        if (blockReadOnlyWrite()) return
        viewModelScope.launch {
            _uiState.update { it.copy(saving = true, message = null) }
            repository.updateExpense(expenseId, draft)
                .onSuccess { expense ->
                    _uiState.update { it.copy(expense = expense, saving = false, message = "已保存", done = true) }
                }
                .onFailure { error -> _uiState.update { it.copy(saving = false, message = error.message ?: "没有保存成功，请稍后再试。") } }
        }
    }

    fun confirm(draft: ExpenseDraft) {
        if (blockReadOnlyWrite()) return
        if (draft.amountCents == null) {
            _uiState.update { it.copy(message = "请先填写金额。") }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(saving = true, message = null) }
            repository.updateExpense(expenseId, draft)
                .onSuccess {
                    repository.confirmExpense(expenseId)
                        .onSuccess { confirmed ->
                            _uiState.update { state -> state.copy(expense = confirmed, saving = false, done = true) }
                        }
                        .onFailure { error ->
                            _uiState.update { state -> state.copy(saving = false, message = error.message ?: "没有确认成功，请稍后再试。") }
                        }
                }
                .onFailure { error -> _uiState.update { it.copy(saving = false, message = error.message ?: "没有保存成功，请稍后再试。") } }
        }
    }

    fun reject() {
        if (blockReadOnlyWrite()) return
        viewModelScope.launch {
            _uiState.update { it.copy(saving = true, message = null) }
            repository.rejectExpense(expenseId)
                .onSuccess { _uiState.update { it.copy(saving = false, done = true) } }
                .onFailure { error -> _uiState.update { it.copy(saving = false, message = error.message ?: "没有删除成功，请稍后再试。") } }
        }
    }

    fun retryOcr() {
        if (blockReadOnlyWrite()) return
        viewModelScope.launch {
            _uiState.update { it.copy(ocrRunning = true, message = null) }
            repository.retryOcr(expenseId)
                .onSuccess { expense ->
                    _uiState.update { it.copy(expense = expense, ocrRunning = false, message = "识别已重试") }
                }
                .onFailure { error ->
                    _uiState.update { it.copy(ocrRunning = false, message = error.message ?: "没有识别成功，请稍后再试。") }
                }
        }
    }

    fun markNotDuplicate() {
        if (blockReadOnlyWrite()) return
        viewModelScope.launch {
            repository.markNotDuplicate(expenseId)
                .onSuccess { expense ->
                    _uiState.update { it.copy(expense = expense, message = "已保留这条账单") }
                }
                .onFailure { error -> _uiState.update { it.copy(message = error.message ?: "暂时没处理成功，请稍后再试。") } }
        }
    }

    fun consumeDone(): Boolean {
        val wasDone = _uiState.value.done
        if (wasDone) {
            _uiState.update { it.copy(done = false) }
        }
        return wasDone
    }

    private fun blockReadOnlyWrite(): Boolean {
        if (repository.canModifyLedger()) {
            _uiState.update { it.copy(readOnly = false) }
            return false
        }
        _uiState.update { it.copy(readOnly = true, saving = false, ocrRunning = false, message = READ_ONLY_LEDGER_MESSAGE) }
        return true
    }
}
