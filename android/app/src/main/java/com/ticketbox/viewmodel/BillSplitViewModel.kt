package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.domain.model.BillSplitInbox
import com.ticketbox.domain.model.BillSplitSent
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * ADR-0029 bill split inbox / sent UI.
 *
 * State is two parallel lists + a transient ``message`` for action
 * results. Actions mutate the lists and return the new lists; we don't
 * do optimistic updates because invitation state transitions are
 * relatively rare and the server is the source of truth.
 */
data class BillSplitUiState(
    val inbox: List<BillSplitInbox> = emptyList(),
    val sent: List<BillSplitSent> = emptyList(),
    val loading: Boolean = false,
    val message: String? = null,
)

class BillSplitViewModel(
    private val repository: ExpenseRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(BillSplitUiState())
    val uiState: StateFlow<BillSplitUiState> = _uiState.asStateFlow()

    fun refresh() {
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, message = null) }
            val inboxResult = repository.fetchBillSplitInbox()
            val sentResult = repository.fetchBillSplitSent()
            _uiState.update {
                it.copy(
                    loading = false,
                    inbox = inboxResult.getOrNull() ?: it.inbox,
                    sent = sentResult.getOrNull() ?: it.sent,
                    message = (inboxResult.exceptionOrNull() ?: sentResult.exceptionOrNull())
                        ?.message,
                )
            }
        }
    }

    fun accept(publicId: String, targetLedgerId: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, message = null) }
            repository.acceptBillSplitInvitation(publicId, targetLedgerId)
                .onSuccess { refresh() }
                .onFailure { err ->
                    _uiState.update { it.copy(loading = false, message = err.message) }
                }
        }
    }

    fun reject(publicId: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, message = null) }
            repository.rejectBillSplitInvitation(publicId)
                .onSuccess { refresh() }
                .onFailure { err ->
                    _uiState.update { it.copy(loading = false, message = err.message) }
                }
        }
    }

    fun cancel(publicId: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, message = null) }
            repository.cancelBillSplitInvitation(publicId)
                .onSuccess { refresh() }
                .onFailure { err ->
                    _uiState.update { it.copy(loading = false, message = err.message) }
                }
        }
    }
}
