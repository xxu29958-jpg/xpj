package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.domain.model.BackgroundTask
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
)

class BackgroundTasksViewModel(
    private val repository: ExpenseRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(BackgroundTasksUiState())
    val uiState: StateFlow<BackgroundTasksUiState> = _uiState.asStateFlow()

    fun refresh() {
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, message = null) }
            repository.fetchBackgroundTasks()
                .onSuccess { tasks ->
                    _uiState.update { it.copy(loading = false, tasks = tasks) }
                }
                .onFailure { err ->
                    _uiState.update {
                        it.copy(loading = false, message = err.toUiText(R.string.background_tasks_message_load_failed))
                    }
                }
        }
    }

    fun cancel(publicId: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(busyTaskId = publicId, message = null) }
            repository.cancelBackgroundTask(publicId)
                .onSuccess {
                    _uiState.update { it.copy(busyTaskId = null, message = UiText.res(R.string.background_tasks_message_cancel_requested)) }
                    refresh()
                }
                .onFailure { err ->
                    _uiState.update {
                        it.copy(busyTaskId = null, message = err.toUiText(R.string.background_tasks_message_cancel_failed))
                    }
                }
        }
    }
}
