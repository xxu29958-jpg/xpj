package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ProtectedImage
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit

data class PendingUiState(
    val items: List<Expense> = emptyList(),
    val thumbnails: Map<Long, ProtectedImage> = emptyMap(),
    val actionInProgressIds: Set<Long> = emptySet(),
    val loading: Boolean = false,
    val uploading: Boolean = false,
    val message: String? = null,
)

class PendingViewModel(
    private val repository: ExpenseRepository,
) : ViewModel() {
    private companion object {
        const val THUMBNAIL_CONCURRENCY = 4
    }

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

    fun uploadScreenshot(fileName: String, contentType: String?, bytes: ByteArray) {
        if (_uiState.value.uploading) return
        viewModelScope.launch {
            _uiState.update { it.copy(uploading = true, message = null) }
            repository.uploadScreenshot(fileName = fileName, contentType = contentType, bytes = bytes)
                .onSuccess {
                    _uiState.update { state ->
                        state.copy(uploading = false, message = "截图已上传，等你确认。")
                    }
                    refresh()
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            uploading = false,
                            message = error.message ?: "没有上传成功，请稍后再试。",
                        )
                    }
                }
        }
    }

    private suspend fun loadThumbnails(expenses: List<Expense>) = coroutineScope {
        val pendingIds = expenses.map { expense -> expense.id }.toSet()
        val missing = expenses.filter { expense ->
            expense.imagePath != null && !_uiState.value.thumbnails.containsKey(expense.id)
        }
        if (missing.isEmpty()) return@coroutineScope

        val limiter = Semaphore(THUMBNAIL_CONCURRENCY)
        val loaded = missing
            .map { expense ->
                async {
                    limiter.withPermit {
                        repository.fetchThumbnail(expense.id)
                            .getOrNull()
                            ?.let { image -> expense.id to image }
                    }
                }
            }
            .awaitAll()
            .filterNotNull()
            .filter { (id, _) -> id in pendingIds }
            .toMap()

        if (loaded.isNotEmpty()) {
            _uiState.update { state ->
                val activeIds = state.items.map { expense -> expense.id }.toSet()
                state.copy(thumbnails = state.thumbnails + loaded.filterKeys { id -> id in activeIds })
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
