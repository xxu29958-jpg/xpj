package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.BackgroundTaskActions
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.domain.model.BackgroundTask
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** Server task history; source bills own review and recognition recovery. */
data class BackgroundTasksUiState(
    val tasks: List<BackgroundTask> = emptyList(),
    val loading: Boolean = false,
    val busyTaskId: String? = null,
    val message: UiText? = null,
    val messageTone: MessageTone = MessageTone.Neutral,
    val access: LedgerAccessContext? = null,
) {
    val canModify: Boolean get() = access?.canModify == true
}

class BackgroundTasksViewModel(
    private val repository: BackgroundTaskActions,
) : ViewModel() {
    private val _uiState = MutableStateFlow(
        BackgroundTasksUiState(access = repository.currentAccess()),
    )
    val uiState: StateFlow<BackgroundTasksUiState> = _uiState.asStateFlow()

    init {
        viewModelScope.launch { repository.observeAccess().collect(::acceptAccess) }
    }

    private fun acceptAccess(updated: LedgerAccessContext?) {
        _uiState.update {
            if (it.access?.binding != updated?.binding) BackgroundTasksUiState(access = updated)
            else it.copy(access = updated)
        }
    }

    private fun refreshAccess(): LedgerAccessContext? = repository.currentAccess().also(::acceptAccess)

    fun sourceExpenseId(publicId: String): Long? {
        refreshAccess() ?: return null
        return _uiState.value.tasks.firstOrNull { it.publicId == publicId }?.sourceExpenseId
    }

    fun refresh() {
        val binding = refreshAccess()?.binding ?: return
        if (_uiState.value.loading) return
        _uiState.update { it.copy(loading = true, message = null, messageTone = MessageTone.Neutral) }
        viewModelScope.launch {
            val result = repository.fetchBackgroundTasks(binding)
            if (refreshAccess()?.binding != binding) return@launch
            result
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
        val currentAccess = refreshAccess() ?: return
        if (!currentAccess.canModify) return
        val current = _uiState.value
        if (current.busyTaskId != null) return
        if (current.tasks.firstOrNull { it.publicId == publicId }?.isCancellable != true) return
        _uiState.update { it.copy(busyTaskId = publicId, message = null, messageTone = MessageTone.Neutral) }
        viewModelScope.launch {
            val result = repository.cancelBackgroundTask(currentAccess.binding, publicId)
            if (refreshAccess()?.binding != currentAccess.binding) return@launch
            result
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
