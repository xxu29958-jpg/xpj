package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.BackgroundTaskActions
import com.ticketbox.domain.model.BackgroundTask
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * ADR-0030 background_tasks UI.
 *
 * Manual refresh + tap-to-cancel. Polling is intentionally not built in;
 * task types like csv_import are operator-initiated and rare, so a passive
 * list with a pull-to-refresh button is enough. Adding a 3-second poll
 * would burn battery for a feature triggered maybe once a month per account.
 */
data class BackgroundTasksUiState(
    val tasks: List<BackgroundTask> = emptyList(),
    val loading: Boolean = false,
    val busyTaskId: String? = null,
    val message: UiText? = null,
    val messageTone: MessageTone = MessageTone.Neutral,
    val canModify: Boolean = false,
)

class BackgroundTasksViewModel(
    private val repository: BackgroundTaskActions,
) : ViewModel() {

    private val _uiState = MutableStateFlow(
        BackgroundTasksUiState(canModify = repository.canModifyLedger()),
    )
    val uiState: StateFlow<BackgroundTasksUiState> = _uiState.asStateFlow()

    fun refresh() {
        if (_uiState.value.loading) return
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    loading = true,
                    message = null,
                    messageTone = MessageTone.Neutral,
                    canModify = repository.canModifyLedger(),
                )
            }
            repository.fetchBackgroundTasks()
                .onSuccess { tasks ->
                    _uiState.update {
                        it.copy(
                            loading = false,
                            tasks = tasks,
                            message = null,
                            messageTone = MessageTone.Neutral,
                        )
                    }
                }
                .onFailure { err ->
                    _uiState.update {
                        val fallback = if (it.tasks.isEmpty()) {
                            R.string.background_tasks_message_load_failed
                        } else {
                            R.string.background_tasks_message_refresh_failed_with_data
                        }
                        it.copy(
                            loading = false,
                            message = err.toUiText(fallback),
                            messageTone = MessageTone.Danger,
                        )
                    }
                }
        }
    }

    fun cancel(publicId: String) {
        val current = _uiState.value
        if (!current.canModify) return
        if (current.busyTaskId != null) return
        if (current.tasks.firstOrNull { it.publicId == publicId }?.isCancellable != true) return
        viewModelScope.launch {
            _uiState.update { it.copy(busyTaskId = publicId, message = null, messageTone = MessageTone.Neutral) }
            repository.cancelBackgroundTask(publicId)
                .onSuccess { updated ->
                    _uiState.update {
                        it.copy(
                            tasks = it.tasks.replaceTask(updated),
                            busyTaskId = null,
                            message = UiText.res(R.string.background_tasks_message_cancel_requested),
                            messageTone = MessageTone.Success,
                        )
                    }
                }
                .onFailure { err ->
                    _uiState.update {
                        it.copy(
                            busyTaskId = null,
                            message = err.toUiText(R.string.background_tasks_message_cancel_failed),
                            messageTone = MessageTone.Danger,
                        )
                    }
                }
        }
    }
}

private fun List<BackgroundTask>.replaceTask(updated: BackgroundTask): List<BackgroundTask> =
    map { task -> if (task.publicId == updated.publicId) updated else task }
