package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.RecycleBinItem
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class RecycleBinUiState(
    val items: List<RecycleBinItem> = emptyList(),
    val shortWindowCount: Int = 0,
    val loading: Boolean = false,
    val loadFailed: Boolean = false,
    val busyItemKey: String? = null,
    val message: UiText? = null,
    val messageTone: MessageTone = MessageTone.Neutral,
    val canModify: Boolean = false,
    val changedRevision: Int = 0,
)

class RecycleBinViewModel(
    private val repository: LedgerRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(
        RecycleBinUiState(canModify = repository.canModifyLedger()),
    )
    val uiState: StateFlow<RecycleBinUiState> = _uiState.asStateFlow()

    fun refresh() {
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    loading = true,
                    loadFailed = false,
                    message = null,
                    messageTone = MessageTone.Neutral,
                    canModify = repository.canModifyLedger(),
                )
            }
            repository.refreshRecycleBin()
                .onSuccess { snapshot ->
                    _uiState.update {
                        it.copy(
                            items = snapshot.items,
                            shortWindowCount = snapshot.shortWindowCount,
                            loading = false,
                            loadFailed = false,
                            messageTone = MessageTone.Neutral,
                            canModify = repository.canModifyLedger(),
                        )
                    }
                }
                .onFailure { err ->
                    _uiState.update {
                        it.copy(
                            loading = false,
                            loadFailed = true,
                            canModify = repository.canModifyLedger(),
                            message = err.toUiText(R.string.recycle_bin_message_load_failed),
                            messageTone = MessageTone.Danger,
                        )
                    }
                }
        }
    }

    fun restore(item: RecycleBinItem) {
        if (!repository.canModifyLedger()) return
        val key = item.busyKey()
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    busyItemKey = key,
                    message = null,
                    messageTone = MessageTone.Neutral,
                )
            }
            repository.restoreRecycleBinItem(item)
                .onSuccess { message ->
                    _uiState.update { it.withRestoredItemRemoved(key) }
                    repository.refreshRecycleBin()
                        .onSuccess { snapshot ->
                            _uiState.update {
                                it.copy(
                                    items = snapshot.items,
                                    shortWindowCount = snapshot.shortWindowCount,
                                    loadFailed = false,
                                    busyItemKey = null,
                                    message = UiText.raw(message),
                                    messageTone = MessageTone.Success,
                                    canModify = repository.canModifyLedger(),
                                )
                            }
                        }
                        .onFailure { err ->
                            _uiState.update {
                                it.copy(
                                    busyItemKey = null,
                                    loadFailed = true,
                                    message = err.toUiText(R.string.recycle_bin_message_load_failed),
                                    messageTone = MessageTone.Danger,
                                    canModify = repository.canModifyLedger(),
                                )
                            }
                        }
                }
                .onFailure { err ->
                    _uiState.update {
                        it.copy(
                            busyItemKey = null,
                            message = err.toUiText(R.string.recycle_bin_message_restore_failed),
                            messageTone = MessageTone.Danger,
                            canModify = repository.canModifyLedger(),
                        )
                    }
                }
        }
    }
}

fun RecycleBinItem.busyKey(): String = "$kind:$resourceId"

private fun RecycleBinUiState.withRestoredItemRemoved(key: String): RecycleBinUiState {
    val remainingItems = items.filterNot { it.busyKey() == key }
    return copy(
        items = remainingItems,
        shortWindowCount = shortWindowCount.coerceIn(0, remainingItems.size),
        loadFailed = false,
        messageTone = MessageTone.Neutral,
        changedRevision = changedRevision + 1,
    )
}
