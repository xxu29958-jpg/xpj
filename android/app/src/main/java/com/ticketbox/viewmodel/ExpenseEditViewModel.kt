package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
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
    val categories: List<String> = emptyList(),
    val imageLoading: Boolean = false,
    val ocrRunning: Boolean = false,
    val saving: Boolean = false,
    val message: String? = null,
    val done: Boolean = false,
)

class ExpenseEditViewModel(
    private val expenseId: Long,
    private val repository: ExpenseRepository,
) : ViewModel() {
    private val _uiState = MutableStateFlow(ExpenseEditUiState())
    val uiState: StateFlow<ExpenseEditUiState> = _uiState.asStateFlow()

    init {
        loadCategories()
        loadThumbnail()
    }

    private fun loadCategories() {
        viewModelScope.launch {
            repository.categories()
                .onSuccess { categories -> _uiState.update { it.copy(categories = categories) } }
        }
    }

    private fun loadThumbnail() {
        viewModelScope.launch {
            _uiState.update { it.copy(imageLoading = true) }
            repository.fetchThumbnail(expenseId)
                .onSuccess { image -> _uiState.update { it.copy(thumbnail = image, imageLoading = false) } }
                .onFailure { _uiState.update { it.copy(imageLoading = false) } }
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
                            message = error.message ?: "原图加载失败",
                        )
                    }
                }
        }
    }

    fun save(draft: ExpenseDraft) {
        viewModelScope.launch {
            _uiState.update { it.copy(saving = true, message = null) }
            repository.updateExpense(expenseId, draft)
                .onSuccess { expense ->
                    _uiState.update { it.copy(expense = expense, saving = false, message = "已保存", done = true) }
                }
                .onFailure { error -> _uiState.update { it.copy(saving = false, message = error.message ?: "保存失败") } }
        }
    }

    fun confirm(draft: ExpenseDraft) {
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
                            _uiState.update { state -> state.copy(saving = false, message = error.message ?: "确认失败") }
                        }
                }
                .onFailure { error -> _uiState.update { it.copy(saving = false, message = error.message ?: "保存失败") } }
        }
    }

    fun reject() {
        viewModelScope.launch {
            _uiState.update { it.copy(saving = true, message = null) }
            repository.rejectExpense(expenseId)
                .onSuccess { _uiState.update { it.copy(saving = false, done = true) } }
                .onFailure { error -> _uiState.update { it.copy(saving = false, message = error.message ?: "删除失败") } }
        }
    }

    fun retryOcr() {
        viewModelScope.launch {
            _uiState.update { it.copy(ocrRunning = true, message = null) }
            repository.retryOcr(expenseId)
                .onSuccess { expense ->
                    _uiState.update { it.copy(expense = expense, ocrRunning = false, message = "识别已重试") }
                }
                .onFailure { error ->
                    _uiState.update { it.copy(ocrRunning = false, message = error.message ?: "识别失败") }
                }
        }
    }

    fun markNotDuplicate() {
        viewModelScope.launch {
            repository.markNotDuplicate(expenseId)
                .onSuccess { expense ->
                    _uiState.update { it.copy(expense = expense, message = "已保留这条账单") }
                }
                .onFailure { error -> _uiState.update { it.copy(message = error.message ?: "操作失败") } }
        }
    }
}
