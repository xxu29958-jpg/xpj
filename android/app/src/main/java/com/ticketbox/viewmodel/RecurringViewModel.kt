package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.RecurringActions
import com.ticketbox.domain.model.RecurringCandidate
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class RecurringUiState(
    val loading: Boolean = false,
    val message: UiText? = null,
    val items: List<RecurringItem> = emptyList(),
    val candidates: List<RecurringCandidate> = emptyList(),
    val canModify: Boolean = true,
)

class RecurringViewModel(
    private val repository: RecurringActions,
) : ViewModel() {
    private val _uiState = MutableStateFlow(RecurringUiState(canModify = repository.canModifyLedger()))
    val uiState: StateFlow<RecurringUiState> = _uiState.asStateFlow()
    private var requestGeneration = 0

    init {
        observeLedgerChanges()
        refresh()
    }

    private fun observeLedgerChanges() {
        viewModelScope.launch {
            repository.observeActiveLedgerId()
                .distinctUntilChanged()
                .drop(1)
                .collect {
                    requestGeneration += 1
                    _uiState.value = RecurringUiState(
                        loading = true,
                        canModify = repository.canModifyLedger(),
                    )
                    refresh()
                }
        }
    }

    fun refresh() {
        viewModelScope.launch {
            val generation = requestGeneration
            _uiState.update { it.copy(loading = true, message = null, canModify = repository.canModifyLedger()) }
            val itemsResult = repository.items(includeArchived = true)
            val candidatesResult = repository.candidates()
            if (requestGeneration != generation) return@launch
            val message = listOf(itemsResult, candidatesResult)
                .firstOrNull { it.isFailure }
                ?.exceptionOrNull()
                ?.toUiText(R.string.recurring_message_action_failed)
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
        if (candidate !in _uiState.value.candidates) {
            _uiState.update { it.copy(message = UiText.res(R.string.recurring_message_candidate_expired)) }
            return
        }
        mutate {
            repository.confirmCandidate(candidate)
        }
    }

    fun pause(publicId: String, expectedRowVersion: Long) {
        mutate {
            repository.pause(publicId, expectedRowVersion)
        }
    }

    fun resume(publicId: String, expectedRowVersion: Long) {
        mutate {
            repository.resume(publicId, expectedRowVersion)
        }
    }

    fun archive(publicId: String) {
        mutate {
            repository.archive(publicId)
        }
    }

    private fun mutate(action: suspend () -> Result<RecurringItem>) {
        if (!repository.canModifyLedger()) {
            _uiState.update { it.copy(message = UiText.res(R.string.common_readonly_ledger), canModify = false) }
            return
        }
        viewModelScope.launch {
            val generation = requestGeneration
            _uiState.update { it.copy(loading = true, message = null) }
            val result = action()
            if (requestGeneration != generation) return@launch
            result.fold(
                onSuccess = {
                    _uiState.update { state -> state.copy(message = UiText.res(R.string.recurring_message_updated)) }
                    refresh()
                },
                onFailure = { error ->
                    _uiState.update {
                        it.copy(
                            loading = false,
                            message = error.toUiText(R.string.recurring_message_action_failed),
                            canModify = repository.canModifyLedger(),
                        )
                    }
                },
            )
        }
    }
}
