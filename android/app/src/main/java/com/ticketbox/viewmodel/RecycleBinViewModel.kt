package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.LedgerRepository
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
    val canModify: Boolean = false,
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
                        )
                    }
                }
        }
    }

    fun restore(item: RecycleBinItem) {
        if (!repository.canModifyLedger()) return
        val key = item.busyKey()
        viewModelScope.launch {
            _uiState.update { it.copy(busyItemKey = key, message = null) }
            repository.restoreRecycleBinItem(item)
                .onSuccess { message ->
                    repository.refreshRecycleBin()
                        .onSuccess { snapshot ->
                            _uiState.update {
                                it.copy(
                                    items = snapshot.items,
                                    shortWindowCount = snapshot.shortWindowCount,
                                    loadFailed = false,
                                    busyItemKey = null,
                                    message = UiText.raw(message),
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
                            canModify = repository.canModifyLedger(),
                        )
                    }
                }
        }
    }
}

fun RecycleBinItem.busyKey(): String = "$kind:$resourceId"
