package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.RecurringActions
import com.ticketbox.domain.model.MessageTone
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
    val messageTone: MessageTone = MessageTone.Neutral,
    val items: List<RecurringItem> = emptyList(),
    val candidates: List<RecurringCandidate> = emptyList(),
    val itemsLoadState: RecurringListLoadState = RecurringListLoadState.Unknown,
    val candidatesLoadState: RecurringListLoadState = RecurringListLoadState.Unknown,
    val canModify: Boolean = true,
)

enum class RecurringListLoadState {
    Unknown,
    Loading,
    Loaded,
    Failed,
}

class RecurringViewModel(
    private val repository: RecurringActions,
    private val onDataChanged: () -> Unit = {},
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
                        itemsLoadState = RecurringListLoadState.Loading,
                        candidatesLoadState = RecurringListLoadState.Loading,
                        canModify = repository.canModifyLedger(),
                    )
                    refresh()
                }
        }
    }

    fun refresh() {
        viewModelScope.launch {
            val generation = requestGeneration
            _uiState.update {
                it.copy(
                    loading = true,
                    itemsLoadState = RecurringListLoadState.Loading,
                    candidatesLoadState = RecurringListLoadState.Loading,
                    message = null,
                    messageTone = MessageTone.Neutral,
                    canModify = repository.canModifyLedger(),
                )
            }
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
                    messageTone = if (message == null) MessageTone.Neutral else MessageTone.Danger,
                    items = itemsResult.getOrElse { state.items },
                    candidates = candidatesResult.getOrElse { state.candidates },
                    itemsLoadState = itemsResult.toRecurringListLoadState(),
                    candidatesLoadState = candidatesResult.toRecurringListLoadState(),
                    canModify = repository.canModifyLedger(),
                )
            }
        }
    }

    fun confirmCandidate(candidate: RecurringCandidate) {
        if (candidate !in _uiState.value.candidates) {
            _uiState.update {
                it.copy(
                    message = UiText.res(R.string.recurring_message_candidate_expired),
                    messageTone = MessageTone.Info,
                )
            }
            return
        }
        mutate(
            action = { repository.confirmCandidate(candidate) },
            onSuccessState = { state, item ->
                state.copy(
                    items = state.items.withRecurringItem(item),
                    candidates = state.candidates.filterNot { it == candidate },
                )
            },
        )
    }

    fun pause(publicId: String, expectedRowVersion: Long) {
        mutate(action = { repository.pause(publicId, expectedRowVersion) })
    }

    fun resume(publicId: String, expectedRowVersion: Long) {
        mutate(action = { repository.resume(publicId, expectedRowVersion) })
    }

    fun archive(publicId: String) {
        mutate(action = { repository.archive(publicId) })
    }

    private fun mutate(
        action: suspend () -> Result<RecurringItem>,
        onSuccessState: (RecurringUiState, RecurringItem) -> RecurringUiState = { state, item ->
            state.copy(items = state.items.withRecurringItem(item))
        },
    ) {
        if (!repository.canModifyLedger()) {
            _uiState.update {
                it.copy(
                    message = UiText.res(R.string.common_readonly_ledger),
                    messageTone = MessageTone.Danger,
                    canModify = false,
                )
            }
            return
        }
        viewModelScope.launch {
            val generation = requestGeneration
            _uiState.update { it.copy(loading = true, message = null, messageTone = MessageTone.Neutral) }
            val result = action()
            if (requestGeneration != generation) return@launch
            result.fold(
                onSuccess = { item ->
                    _uiState.update { state ->
                        onSuccessState(
                            state.copy(
                                loading = false,
                                message = UiText.res(R.string.recurring_message_updated),
                                messageTone = MessageTone.Success,
                                canModify = repository.canModifyLedger(),
                            ),
                            item,
                        )
                    }
                    onDataChanged()
                    refresh()
                },
                onFailure = { error ->
                    _uiState.update {
                        it.copy(
                            loading = false,
                            message = error.toUiText(R.string.recurring_message_action_failed),
                            messageTone = MessageTone.Danger,
                            canModify = repository.canModifyLedger(),
                        )
                    }
                },
            )
        }
    }
}

private fun <T> Result<T>.toRecurringListLoadState(): RecurringListLoadState =
    if (isSuccess) RecurringListLoadState.Loaded else RecurringListLoadState.Failed

private fun List<RecurringItem>.withRecurringItem(item: RecurringItem): List<RecurringItem> =
    if (any { it.publicId == item.publicId }) {
        map { existing -> if (existing.publicId == item.publicId) item else existing }
    } else {
        listOf(item) + this
    }
