package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.RecurringActions
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.RecurringCandidate
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
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
    private val _uiState = MutableStateFlow(RecurringUiState(canModify = false))
    val uiState: StateFlow<RecurringUiState> = _uiState.asStateFlow()
    private var requestGeneration = 0
    private var refreshGeneration = 0
    private var activeBinding: LogicalSessionBinding? = null
    private var activeCanModify = false

    init {
        viewModelScope.launch {
            repository.observeActiveLedgerAccess()
                .distinctUntilChanged()
                .collect { access ->
                    activeBinding = access?.binding
                    activeCanModify = access?.canModify ?: false
                    requestGeneration += 1
                    _uiState.value = RecurringUiState(
                        loading = access != null,
                        itemsLoadState = if (access == null) {
                            RecurringListLoadState.Unknown
                        } else {
                            RecurringListLoadState.Loading
                        },
                        candidatesLoadState = if (access == null) {
                            RecurringListLoadState.Unknown
                        } else {
                            RecurringListLoadState.Loading
                        },
                        canModify = access?.canModify ?: false,
                    )
                    if (access != null) refresh()
                }
        }
    }

    fun refresh() {
        val binding = activeBinding ?: return
        val generation = requestGeneration
        val refresh = ++refreshGeneration
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    loading = true,
                    itemsLoadState = RecurringListLoadState.Loading,
                    candidatesLoadState = RecurringListLoadState.Loading,
                    message = null,
                    messageTone = MessageTone.Neutral,
                    canModify = activeCanModify,
                )
            }
            val itemsResult = repository.items(binding, includeArchived = true)
            val candidatesResult = repository.candidates(binding)
            if (requestGeneration != generation || refreshGeneration != refresh) return@launch
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
                    canModify = activeCanModify,
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
            action = { binding -> repository.confirmCandidate(binding, candidate) },
            onSuccessState = { state, item ->
                state.copy(
                    items = state.items.withRecurringItem(item),
                    candidates = state.candidates.filterNot { it == candidate },
                )
            },
        )
    }

    fun pause(publicId: String, expectedRowVersion: Long) {
        mutate(action = { binding -> repository.pause(binding, publicId, expectedRowVersion) })
    }

    fun resume(publicId: String, expectedRowVersion: Long) {
        mutate(action = { binding -> repository.resume(binding, publicId, expectedRowVersion) })
    }

    fun archive(publicId: String) {
        mutate(action = { binding -> repository.archive(binding, publicId) })
    }

    private fun mutate(
        action: suspend (LogicalSessionBinding) -> Result<RecurringItem>,
        onSuccessState: (RecurringUiState, RecurringItem) -> RecurringUiState = { state, item ->
            state.copy(items = state.items.withRecurringItem(item))
        },
    ) {
        val binding = activeBinding
        if (binding == null || !repository.canModifyLedger()) {
            _uiState.update {
                it.copy(
                    message = UiText.res(R.string.common_readonly_ledger),
                    messageTone = MessageTone.Danger,
                    canModify = false,
                )
            }
            return
        }
        val generation = requestGeneration
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, message = null, messageTone = MessageTone.Neutral) }
            val result = action(binding)
            if (requestGeneration != generation) return@launch
            result.fold(
                onSuccess = { item ->
                    _uiState.update { state ->
                        onSuccessState(
                            state.copy(
                                loading = false,
                                message = UiText.res(R.string.recurring_message_updated),
                                messageTone = MessageTone.Success,
                                canModify = activeCanModify,
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
                            canModify = activeCanModify,
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
