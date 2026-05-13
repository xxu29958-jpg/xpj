package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.RecurringRepository
import com.ticketbox.domain.model.RecurringCandidate
import com.ticketbox.domain.model.RecurringItem
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class RecurringUiState(
    val loading: Boolean = false,
    val message: String? = null,
    val items: List<RecurringItem> = emptyList(),
    val candidates: List<RecurringCandidate> = emptyList(),
    val canModify: Boolean = true,
)

class RecurringViewModel(
    private val repository: RecurringRepository,
) : ViewModel() {
    private val _uiState = MutableStateFlow(RecurringUiState(canModify = repository.canModifyLedger()))
    val uiState: StateFlow<RecurringUiState> = _uiState.asStateFlow()

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, message = null, canModify = repository.canModifyLedger()) }
            val itemsResult = repository.items(includeArchived = true)
            val candidatesResult = repository.candidates()
            val message = listOf(itemsResult, candidatesResult)
                .firstOrNull { it.isFailure }
                ?.exceptionOrNull()
                ?.message
            _uiState.update { state ->
                state.copy(
                    loading = false,
                    message = message,
                    items = itemsResult.getOrElse { state.items },
                    candidates = candidatesResult.getOrElse { state.candidates },
                    canModify = repository.canModifyLedger(),
                )
            }
        }
    }

    fun confirmCandidate(candidate: RecurringCandidate) {
        mutate {
            repository.confirmCandidate(candidate)
        }
    }

    fun pause(publicId: String) {
        mutate {
            repository.pause(publicId)
        }
    }

    fun resume(publicId: String) {
        mutate {
            repository.resume(publicId)
        }
    }

    fun archive(publicId: String) {
        mutate {
            repository.archive(publicId)
        }
    }

    private fun mutate(action: suspend () -> Result<RecurringItem>) {
        if (!repository.canModifyLedger()) {
            _uiState.update { it.copy(message = "当前角色为只读，无法修改账本。", canModify = false) }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, message = null) }
            val result = action()
            result.fold(
                onSuccess = {
                    _uiState.update { state -> state.copy(message = "固定支出已更新。") }
                    refresh()
                },
                onFailure = { error ->
                    _uiState.update {
                        it.copy(
                            loading = false,
                            message = error.message ?: "操作失败。",
                            canModify = repository.canModifyLedger(),
                        )
                    }
                },
            )
        }
    }
}
