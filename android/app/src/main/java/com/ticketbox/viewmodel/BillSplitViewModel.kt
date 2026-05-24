package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.domain.model.BillSplitInbox
import com.ticketbox.domain.model.BillSplitSent
import com.ticketbox.domain.model.ledgerRoleCanModify
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
 *
 * Also owns ``candidateTargetLedgerIds``: the writable ledgers an
 * inbox row can be accepted into. Computed from a fresh
 * ``refreshLedgers()`` call so a fresh install / cold start doesn't
 * leave the accept action disabled because cache was empty (codex
 * P2 review, PR #88).
 */
data class BillSplitUiState(
    val inbox: List<BillSplitInbox> = emptyList(),
    val sent: List<BillSplitSent> = emptyList(),
    val candidateTargetLedgerIds: List<String> = emptyList(),
    val loading: Boolean = false,
    val message: String? = null,
)

class BillSplitViewModel(
    private val expenseRepository: ExpenseRepository,
    private val ledgerRepository: LedgerRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(
        BillSplitUiState(
            candidateTargetLedgerIds = ledgerRepository.cachedLedgers()
                .filter { ledgerRoleCanModify(it.role) }
                .map { it.ledgerId },
        ),
    )
    val uiState: StateFlow<BillSplitUiState> = _uiState.asStateFlow()

    fun refresh() {
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, message = null) }
            // Refresh ledger membership in parallel so the accept-target
            // dropdown is never empty just because cache was cold. Failure
            // is non-fatal — we fall back to whatever cache held.
            ledgerRepository.refreshLedgers()
                .onSuccess { ledgers ->
                    _uiState.update {
                        it.copy(
                            candidateTargetLedgerIds = ledgers
                                .filter { l -> ledgerRoleCanModify(l.role) }
                                .map { l -> l.ledgerId },
                        )
                    }
                }
            val inboxResult = expenseRepository.fetchBillSplitInbox()
            val sentResult = expenseRepository.fetchBillSplitSent()
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
            expenseRepository.acceptBillSplitInvitation(publicId, targetLedgerId)
                .onSuccess { refresh() }
                .onFailure { err ->
                    _uiState.update { it.copy(loading = false, message = err.message) }
                }
        }
    }

    fun reject(publicId: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, message = null) }
            expenseRepository.rejectBillSplitInvitation(publicId)
                .onSuccess { refresh() }
                .onFailure { err ->
                    _uiState.update { it.copy(loading = false, message = err.message) }
                }
        }
    }

    fun cancel(publicId: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, message = null) }
            expenseRepository.cancelBillSplitInvitation(publicId)
                .onSuccess { refresh() }
                .onFailure { err ->
                    _uiState.update { it.copy(loading = false, message = err.message) }
                }
        }
    }
}
